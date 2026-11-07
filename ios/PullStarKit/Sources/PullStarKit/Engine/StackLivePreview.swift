import Foundation
import CoreGraphics
import ImageIO

/// Manages periodically downscaled tone-mapped JPEG previews of the running star-trail stack.
/// Matches Python backend/engine/live_preview.py.
public final class LivePreviewPublisher: @unchecked Sendable {
    public typealias PreviewCallback = @Sendable (Data, Int) -> Void

    private let lock = NSLock()
    private var lastPublishTime: TimeInterval = 0
    public private(set) var revision: Int = 0
    public let minimumInterval: TimeInterval
    public let destinationURL: URL?
    public let callback: PreviewCallback?

    public init(
        destinationURL: URL? = nil,
        minimumInterval: TimeInterval = 0.25,
        callback: PreviewCallback? = nil
    ) {
        self.destinationURL = destinationURL
        self.minimumInterval = minimumInterval
        self.callback = callback
    }

    /// Publishes a preview from the accumulator if the throttle interval has elapsed or if `force` is true.
    /// Returns the JPEG data and revision counter if published, or nil if throttled/failed.
    @discardableResult
    public func publish(accumulator: PixelImage, force: Bool = false) -> (Data, Int)? {
        lock.lock()
        let now = ProcessInfo.processInfo.systemUptime
        if !force && (now - lastPublishTime < minimumInterval) {
            lock.unlock()
            return nil
        }
        lock.unlock()

        guard let jpegData = Self.renderJPEG(from: accumulator) else {
            return nil
        }

        lock.lock()
        lastPublishTime = now
        revision += 1
        let currentRevision = revision
        lock.unlock()

        // Write atomically if destination URL is specified
        if let dest = destinationURL {
            let temp = dest.deletingLastPathComponent()
                .appendingPathComponent(".\(dest.deletingPathExtension().lastPathComponent).tmp.\(dest.pathExtension)")
            do {
                try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
                try jpegData.write(to: temp, options: .atomic)
                _ = try? FileManager.default.removeItem(at: dest)
                try FileManager.default.moveItem(at: temp, to: dest)
            } catch {
                // Ignore transient filesystem errors in preview generation
            }
        }

        callback?(jpegData, currentRevision)
        return (jpegData, currentRevision)
    }

    // MARK: - Tone Mapping and JPEG Rendering

    /// Linear -> sRGB-encoded (0...1) via a 64K-entry table. Python's live preview operates on
    /// display-encoded pixels, so the percentile stretch must too (backend/engine/live_preview.py).
    private static let encodeLUT: [Float] = (0..<65536).map { ImageWriter.linearToSRGB(Float($0) / 65535) }
    @inline(__always) static func encode(_ v: Float) -> Float {
        guard v > 0 else { return 0 }
        return encodeLUT.withUnsafeBufferPointer { $0[min(65535, Int(v * 65535))] }
    }

    /// Renders a display-ready tone-mapped JPEG from a linear float accumulator image.
    public static func renderJPEG(from image: PixelImage) -> Data? {
        guard image.width > 0 && image.height > 0 && !image.data.isEmpty else {
            return nil
        }

        let w = image.width
        let h = image.height
        let ch = image.channels

        // 1. Calculate tone scale using a downsampled sample (max dim 512)
        let sampleMaxDim = 512
        let step = max(1, max(w, h) / sampleMaxDim)

        var positiveSamples: [Float] = []
        positiveSamples.reserveCapacity((w / step) * (h / step))

        var maxVal: Float = 0
        for y in stride(from: 0, to: h, by: step) {
            for x in stride(from: 0, to: w, by: step) {
                let idx = (y * w + x) * ch
                for c in 0..<min(ch, 3) {
                    let v = Self.encode(image.data[idx + c])
                    if v.isFinite && v > 0 {
                        positiveSamples.append(v)
                        if v > maxVal { maxVal = v }
                    }
                }
            }
        }

        guard maxVal > 0 else {
            return nil
        }

        var scale: Float = maxVal
        if !positiveSamples.isEmpty {
            positiveSamples.sort()
            let idx997 = min(positiveSamples.count - 1, Int(Double(positiveSamples.count) * 0.997))
            let p997 = positiveSamples[idx997]
            if p997.isFinite && p997 > 0 {
                scale = p997
            }
        }

        let invScale = 255.0 / scale

        // 2. Downscale to max display dimension 2048 if needed
        let maxDisplayDim = 2048
        let displayScale = min(1.0, Double(maxDisplayDim) / Double(max(w, h)))
        let outW = max(1, Int(round(Double(w) * displayScale)))
        let outH = max(1, Int(round(Double(h) * displayScale)))

        var rgbBytes = [UInt8](repeating: 0, count: outW * outH * 3)

        for dy in 0..<outH {
            let sy = min(h - 1, Int(Double(dy) / displayScale))
            for dx in 0..<outW {
                let sx = min(w - 1, Int(Double(dx) / displayScale))
                let srcIdx = (sy * w + sx) * ch
                let dstIdx = (dy * outW + dx) * 3

                if ch >= 3 {
                    let r = min(255.0, max(0.0, Self.encode(image.data[srcIdx]) * invScale))
                    let g = min(255.0, max(0.0, Self.encode(image.data[srcIdx + 1]) * invScale))
                    let b = min(255.0, max(0.0, Self.encode(image.data[srcIdx + 2]) * invScale))
                    rgbBytes[dstIdx] = UInt8(r)
                    rgbBytes[dstIdx + 1] = UInt8(g)
                    rgbBytes[dstIdx + 2] = UInt8(b)
                } else {
                    let y = min(255.0, max(0.0, Self.encode(image.data[srcIdx]) * invScale))
                    let byteY = UInt8(y)
                    rgbBytes[dstIdx] = byteY
                    rgbBytes[dstIdx + 1] = byteY
                    rgbBytes[dstIdx + 2] = byteY
                }
            }
        }

        // 3. Encode to JPEG using ImageIO
        return encodeJPEG(rgbBytes: rgbBytes, width: outW, height: outH, quality: 0.88)
    }

    private static func encodeJPEG(
        rgbBytes: [UInt8],
        width: Int,
        height: Int,
        quality: Float
    ) -> Data? {
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue)

        guard let provider = CGDataProvider(data: Data(rgbBytes) as CFData),
              let cgImage = CGImage(
                width: width,
                height: height,
                bitsPerComponent: 8,
                bitsPerPixel: 24,
                bytesPerRow: width * 3,
                space: colorSpace,
                bitmapInfo: bitmapInfo,
                provider: provider,
                decode: nil,
                shouldInterpolate: true,
                intent: .defaultIntent
              ) else {
            return nil
        }

        let outputData = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            outputData as CFMutableData,
            "public.jpeg" as CFString,
            1,
            nil
        ) else {
            return nil
        }

        let options: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: quality
        ]
        CGImageDestinationAddImage(destination, cgImage, options as CFDictionary)
        guard CGImageDestinationFinalize(destination) else {
            return nil
        }

        return outputData as Data
    }
}
