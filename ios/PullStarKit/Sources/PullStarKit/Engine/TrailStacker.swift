import Foundation
import CoreGraphics
import Accelerate

/// Blend modes supported by the star trail stacker.
public enum TrailBlendMode: String, Sendable, CaseIterable {
    case lighten
    case add
}

/// Helpers for synthetic trail effects matching Python core/trail_effects.py and core/video_schedule.py.
public enum TrailEffects {
    /// Validates and normalizes tail taper and angle threshold settings.
    public static func validateTailSettings(
        taperStrength: Double,
        angleThreshold: Double
    ) throws -> (taper: Double, threshold: Double) {
        guard (0.0...1.0).contains(taperStrength) else {
            throw WarpError.invalidDimensions("Tail taper strength must be between 0 and 1, got \(taperStrength)")
        }
        guard (0.0...360.0).contains(angleThreshold) else {
            throw WarpError.invalidDimensions("Tail angle threshold must be between 0 and 360 degrees, got \(angleThreshold)")
        }
        return (taperStrength, angleThreshold)
    }

    /// Determines whether a synthetic rotation angle is within the cutoff threshold.
    public static func withinTailAngle(angleDegrees: Double, thresholdDegrees: Double) -> Bool {
        thresholdDegrees <= 0.0 || abs(angleDegrees) <= thresholdDegrees + 1e-9
    }

    /// Calculates opacity for a synthetic state.
    public static func tailOpacity(
        angleDegrees: Double,
        spanDegrees: Double,
        taperStrength: Double
    ) -> Double {
        if taperStrength <= 0.0 || spanDegrees <= 1e-9 {
            return 1.0
        }
        let progress = min(1.0, max(0.0, abs(angleDegrees) / spanDegrees))
        return max(0.0, 1.0 - taperStrength * progress)
    }

    /// Returns up to `count` items from `items`, retaining the first and last states.
    public static func evenlySpaced<T>(_ items: [T], count: Int) -> [T] {
        let count = max(0, count)
        if items.isEmpty || count == 0 { return [] }
        if count >= items.count { return items }
        if count == 1 { return [items[items.count - 1]] }
        var positions = Set<Int>()
        for i in 0..<count {
            let pos = Int(round(Double(i) * Double(items.count - 1) / Double(count - 1)))
            positions.insert(pos)
        }
        return positions.sorted().map { items[$0] }
    }
}

/// Foreground / sky segmentation mask generator.
public enum ForegroundMaskGenerator {
    /// Generates a float sky mask (1.0 = sky, 0.0 = ground) from a reference aligned frame.
    public static func generateSkyMask(from image: PixelImage) -> [Float] {
        let count = image.width * image.height
        guard count > 0 && image.channels >= 3 else {
            return [Float](repeating: 1.0, count: count)
        }

        // 1. Calculate grayscale luma (Y) and saturation (S)
        var luma = [Float](repeating: 0, count: count)
        var isSky = [Float](repeating: 0, count: count)

        let ch = image.channels
        var histogram = [Int](repeating: 0, count: 256)

        for p in 0..<count {
            let r = image.data[p * ch]
            let g = image.data[p * ch + 1]
            let b = image.data[p * ch + 2]

            let y = 0.299 * r + 0.587 * g + 0.114 * b
            luma[p] = y

            let maxVal = max(r, max(g, b))
            let minVal = min(r, min(g, b))
            let sat = maxVal > 1e-5 ? (maxVal - minVal) / maxVal : 0

            let bin = max(0, min(255, Int(y * 255.0)))
            histogram[bin] += 1

            // Sky criterion: low saturation night sky or bright twilight/light pollution
            if sat < 0.4 || y > 0.8 {
                isSky[p] = 1.0
            }
        }

        // 2. Otsu thresholding on luma
        let total = Float(count)
        var sum: Float = 0
        for i in 0..<256 { sum += Float(i) * Float(histogram[i]) }

        var sumB: Float = 0
        var wB: Float = 0
        var maxVariance: Float = 0
        var otsuThreshold: Float = 0.1

        for i in 0..<256 {
            wB += Float(histogram[i])
            if wB == 0 { continue }
            let wF = total - wB
            if wF == 0 { break }

            sumB += Float(i) * Float(histogram[i])
            let mB = sumB / wB
            let mF = (sum - sumB) / wF
            let between = wB * wF * (mB - mF) * (mB - mF)
            if between > maxVariance {
                maxVariance = between
                otsuThreshold = Float(i) / 255.0
            }
        }

        // Combine Otsu threshold with saturation
        for p in 0..<count {
            if luma[p] >= otsuThreshold {
                isSky[p] = 1.0
            }
        }

        // 3. Smooth / feather mask with 5x5 separable box filter
        var smoothed = [Float](repeating: 0, count: count)
        let w = image.width
        let h = image.height

        for y in 0..<h {
            for x in 0..<w {
                var sumVal: Float = 0
                var sampleCount: Float = 0
                for dy in -2...2 {
                    let sy = y + dy
                    if sy >= 0 && sy < h {
                        for dx in -2...2 {
                            let sx = x + dx
                            if sx >= 0 && sx < w {
                                sumVal += isSky[sy * w + sx]
                                sampleCount += 1.0
                            }
                        }
                    }
                }
                smoothed[y * w + x] = sumVal / sampleCount
            }
        }

        return smoothed
    }
}

/// Metadata saved in a stack checkpoint.
public struct StackCheckpointMetadata: Codable, Sendable {
    public var lastFrameIndex: Int
    public var width: Int
    public var height: Int
    public var channels: Int
    public var blendMode: String
    public var tailTaperStrength: Double
    public var tailAngleThreshold: Double
    public var signature: String
}

/// Manages stacking of aligned frames, blend modes, foreground masks, gap filling,
/// synthetic trail extensions, and checkpoints.
public final class TrailStacker: @unchecked Sendable {
    public let width: Int
    public let height: Int
    public let channels: Int
    public let blendMode: TrailBlendMode

    private let lock = NSLock()
    public private(set) var accumulator: PixelImage
    public private(set) var skyMask: [Float]?

    public init(
        width: Int,
        height: Int,
        channels: Int = 3,
        blendMode: TrailBlendMode = .lighten
    ) {
        self.width = width
        self.height = height
        self.channels = channels
        self.blendMode = blendMode
        self.accumulator = PixelImage(width: width, height: height, channels: channels)
    }

    /// Sets or updates the sky mask (1.0 = sky, 0.0 = ground).
    public func setSkyMask(_ mask: [Float]) {
        lock.lock()
        defer { lock.unlock() }
        self.skyMask = mask
    }

    /// Compute and set the sky mask from an aligned reference frame.
    public func computeSkyMask(from referenceFrame: PixelImage) {
        let mask = ForegroundMaskGenerator.generateSkyMask(from: referenceFrame)
        setSkyMask(mask)
    }

    /// Blends a frame into the accumulator.
    public func blend(
        frame: PixelImage,
        isSynthetic: Bool = false,
        fade: Float = 1.0,
        useMask: Bool = false
    ) {
        lock.lock()
        defer { lock.unlock() }

        guard frame.width == width && frame.height == height && frame.channels == channels else {
            return
        }

        let count = width * height
        let ch = channels
        let mask = (useMask && isSynthetic) ? skyMask : nil
        let isAdd = (blendMode == .add) && !isSynthetic

        frame.data.withUnsafeBufferPointer { frameBuf in
            guard let fBase = frameBuf.baseAddress else { return }
            accumulator.data.withUnsafeMutableBufferPointer { accBuf in
                guard let aBase = accBuf.baseAddress else { return }

                for p in 0..<count {
                    let m = mask?[p] ?? 1.0
                    if m <= 0.0 { continue }
                    let pixelFade = fade * m

                    for c in 0..<ch {
                        let idx = p * ch + c
                        let val = fBase[idx] * pixelFade
                        if isAdd {
                            aBase[idx] += val
                        } else {
                            let curr = aBase[idx]
                            aBase[idx] = max(curr, val)
                        }
                    }
                }
            }
        }
    }

    /// Returns a copy of the current accumulator.
    public func currentSnapshot() -> PixelImage {
        lock.lock()
        defer { lock.unlock() }
        return accumulator
    }

    /// Restores the accumulator from a given pixel image.
    public func restore(from image: PixelImage) {
        lock.lock()
        defer { lock.unlock() }
        guard image.width == width && image.height == height && image.channels == channels else {
            return
        }
        self.accumulator = image
    }

    // MARK: - Checkpointing

    /// Saves a checkpoint to the specified directory.
    public func saveCheckpoint(
        to directory: URL,
        frameIndex: Int,
        config: JobConfig
    ) throws {
        lock.lock()
        let currentImage = accumulator
        lock.unlock()

        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let metadata = StackCheckpointMetadata(
            lastFrameIndex: frameIndex,
            width: width,
            height: height,
            channels: channels,
            blendMode: blendMode.rawValue,
            tailTaperStrength: config.tailTaperStrength,
            tailAngleThreshold: config.tailAngleThreshold,
            signature: "\(width)x\(height)_\(config.outputBaseName)"
        )

        let metaURL = directory.appendingPathComponent("checkpoint.json")
        let dataURL = directory.appendingPathComponent("accumulator.bin")

        let metaData = try JSONEncoder().encode(metadata)
        try metaData.write(to: metaURL, options: .atomic)

        let byteCount = currentImage.data.count * MemoryLayout<Float>.stride
        let rawData = currentImage.data.withUnsafeBufferPointer { buffer in
            Data(bytes: buffer.baseAddress!, count: byteCount)
        }
        try rawData.write(to: dataURL, options: .atomic)
    }

    /// Attempts to resume from a checkpoint directory.
    /// Returns the last processed frame index if successful, or nil.
    public func resumeCheckpoint(
        from directory: URL,
        config: JobConfig
    ) -> Int? {
        let metaURL = directory.appendingPathComponent("checkpoint.json")
        let dataURL = directory.appendingPathComponent("accumulator.bin")

        guard FileManager.default.fileExists(atPath: metaURL.path),
              FileManager.default.fileExists(atPath: dataURL.path) else {
            return nil
        }

        do {
            let metaData = try Data(contentsOf: metaURL)
            let metadata = try JSONDecoder().decode(StackCheckpointMetadata.self, from: metaData)

            guard metadata.width == width &&
                  metadata.height == height &&
                  metadata.channels == channels &&
                  metadata.blendMode == blendMode.rawValue &&
                  metadata.tailTaperStrength == config.tailTaperStrength &&
                  metadata.tailAngleThreshold == config.tailAngleThreshold else {
                return nil
            }

            let rawData = try Data(contentsOf: dataURL)
            let expectedBytes = width * height * channels * MemoryLayout<Float>.stride
            guard rawData.count == expectedBytes else { return nil }

            var loadedFloats = [Float](repeating: 0, count: width * height * channels)
            _ = loadedFloats.withUnsafeMutableBytes { ptr in
                rawData.copyBytes(to: ptr)
            }

            lock.lock()
            self.accumulator = PixelImage(
                width: width,
                height: height,
                channels: channels,
                data: loadedFloats
            )
            lock.unlock()

            return metadata.lastFrameIndex
        } catch {
            return nil
        }
    }
}
