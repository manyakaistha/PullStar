import Foundation
import AVFoundation
import CoreMedia
import CoreVideo
import CoreGraphics
import Accelerate

/// Errors that can occur during video encoding.
public enum VideoWriterError: Error, LocalizedError, Sendable {
    case invalidDimensions(String)
    case invalidConfiguration(String)
    case writerFailed(String)
    case pixelBufferCreationFailed(String)
    case aborted

    public var errorDescription: String? {
        switch self {
        case .invalidDimensions(let msg): return "Invalid video dimensions: \(msg)"
        case .invalidConfiguration(let msg): return "Invalid video configuration: \(msg)"
        case .writerFailed(let msg): return "AVAssetWriter failed: \(msg)"
        case .pixelBufferCreationFailed(let msg): return "Failed to create pixel buffer: \(msg)"
        case .aborted: return "Video writing was cancelled or aborted"
        }
    }
}

/// Hardware-accelerated AVAssetWriter pipeline producing H.264, HEVC, or ProRes star trail videos.
public final class TrailVideoWriter: @unchecked Sendable {
    public let outputURL: URL
    public let targetWidth: Int
    public let targetHeight: Int
    public let fps: Int
    public let quality: VideoQuality
    public let container: VideoFormat
    public let fileType: AVFileType

    private let assetWriter: AVAssetWriter
    private let writerInput: AVAssetWriterInput
    private let pixelBufferAdaptor: AVAssetWriterInputPixelBufferAdaptor
    private let lock = NSLock()
    private var frameCount: Int64 = 0
    private var isSessionStarted = false
    private var isFinished = false

    /// Computes target even dimensions fitting the resolution preset.
    public static func fitDimensions(
        width: Int,
        height: Int,
        resolution: Resolution
    ) -> (width: Int, height: Int) {
        let limit: Int? = switch resolution {
        case .source: nil
        case .k4: 3840
        case .k2: 2560
        case .p1080: 1920
        case .p720: 1280
        }
        let w = max(2, width)
        let h = max(2, height)
        guard let limit = limit, max(w, h) > limit else {
            return (w - w % 2, h - h % 2)
        }
        let scale = Double(limit) / Double(max(w, h))
        let outW = max(2, Int(round(Double(w) * scale)) / 2 * 2)
        let outH = max(2, Int(round(Double(h) * scale)) / 2 * 2)
        return (outW, outH)
    }

    /// Determines the container and file extension for the given quality and format settings.
    public static func resolveContainer(
        quality: VideoQuality,
        format: VideoFormat
    ) -> (fileType: AVFileType, fileExtension: String) {
        if quality == .prores || format == .mov {
            return (.mov, "mov")
        }
        return (.mp4, "mp4")
    }

    public init(
        destinationURL: URL,
        sourceWidth: Int,
        sourceHeight: Int,
        fps: Int = 30,
        quality: VideoQuality = .high,
        format: VideoFormat = .auto,
        resolution: Resolution = .source
    ) throws {
        let (outW, outH) = Self.fitDimensions(width: sourceWidth, height: sourceHeight, resolution: resolution)
        guard outW > 0 && outH > 0 && outW % 2 == 0 && outH % 2 == 0 else {
            throw VideoWriterError.invalidDimensions("Width \(outW) and Height \(outH) must be positive even integers")
        }

        let (resolvedFileType, ext) = Self.resolveContainer(quality: quality, format: format)
        let finalURL = destinationURL.deletingPathExtension().appendingPathExtension(ext)

        self.outputURL = finalURL
        self.targetWidth = outW
        self.targetHeight = outH
        self.fps = max(1, min(120, fps))
        self.quality = quality
        self.container = format
        self.fileType = resolvedFileType

        // Remove existing file at destination if needed
        if FileManager.default.fileExists(atPath: finalURL.path) {
            try? FileManager.default.removeItem(at: finalURL)
        }

        do {
            try FileManager.default.createDirectory(at: finalURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            self.assetWriter = try AVAssetWriter(outputURL: finalURL, fileType: resolvedFileType)
        } catch {
            throw VideoWriterError.writerFailed("Failed to initialize AVAssetWriter: \(error.localizedDescription)")
        }

        // Codec selection and compression settings
        var outputSettings: [String: Any] = [
            AVVideoWidthKey: outW,
            AVVideoHeightKey: outH
        ]

        let numPixels = Double(outW * outH)

        switch quality {
        case .prores:
            outputSettings[AVVideoCodecKey] = AVVideoCodecType.proRes422HQ

        case .hevc:
            outputSettings[AVVideoCodecKey] = AVVideoCodecType.hevc
            let bitrate = Int(numPixels * Double(fps) * 0.18)
            outputSettings[AVVideoCompressionPropertiesKey] = [
                AVVideoAverageBitRateKey: bitrate,
                AVVideoExpectedSourceFrameRateKey: fps
            ]

        case .lossless:
            // High bitrate HEVC or ProRes for visually lossless master
            if resolvedFileType == .mov {
                outputSettings[AVVideoCodecKey] = AVVideoCodecType.proRes422HQ
            } else {
                outputSettings[AVVideoCodecKey] = AVVideoCodecType.hevc
                let bitrate = Int(numPixels * Double(fps) * 0.40)
                outputSettings[AVVideoCompressionPropertiesKey] = [
                    AVVideoAverageBitRateKey: bitrate,
                    AVVideoExpectedSourceFrameRateKey: fps
                ]
            }

        case .high:
            outputSettings[AVVideoCodecKey] = AVVideoCodecType.h264
            let bitrate = Int(numPixels * Double(fps) * 0.15)
            outputSettings[AVVideoCompressionPropertiesKey] = [
                AVVideoAverageBitRateKey: bitrate,
                AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
                AVVideoExpectedSourceFrameRateKey: fps
            ]

        case .medium:
            outputSettings[AVVideoCodecKey] = AVVideoCodecType.h264
            let bitrate = Int(numPixels * Double(fps) * 0.08)
            outputSettings[AVVideoCompressionPropertiesKey] = [
                AVVideoAverageBitRateKey: bitrate,
                AVVideoProfileLevelKey: AVVideoProfileLevelH264MainAutoLevel,
                AVVideoExpectedSourceFrameRateKey: fps
            ]
        }

        self.writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: outputSettings)
        self.writerInput.expectsMediaDataInRealTime = false

        let sourceBufferAttributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: outW,
            kCVPixelBufferHeightKey as String: outH,
            kCVPixelBufferCGImageCompatibilityKey as String: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
        ]

        self.pixelBufferAdaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: writerInput,
            sourcePixelBufferAttributes: sourceBufferAttributes
        )

        guard assetWriter.canAdd(writerInput) else {
            throw VideoWriterError.invalidConfiguration("Cannot add video input to asset writer")
        }
        assetWriter.add(writerInput)

        guard assetWriter.startWriting() else {
            let reason = assetWriter.error?.localizedDescription ?? "Unknown error"
            throw VideoWriterError.writerFailed("startWriting failed: \(reason)")
        }
    }

    /// Writes one snapshot of the accumulator to the video, repeating it `repeats` times.
    public func writeSnapshot(image: PixelImage, repeats: Int = 1) throws {
        lock.lock()
        defer { lock.unlock() }

        guard !isFinished else { return }

        if !isSessionStarted {
            assetWriter.startSession(atSourceTime: .zero)
            isSessionStarted = true
        }

        guard let pixelBuffer = createPixelBuffer(from: image) else {
            throw VideoWriterError.pixelBufferCreationFailed("Failed to convert image to pixel buffer")
        }

        let repeatCount = max(1, repeats)
        for _ in 0..<repeatCount {
            var waitLoops = 0
            while !writerInput.isReadyForMoreMediaData {
                waitLoops += 1
                if waitLoops > 200 {
                    Thread.sleep(forTimeInterval: 0.005)
                }
                if waitLoops > 1000 {
                    throw VideoWriterError.writerFailed("Timed out waiting for writer ready state")
                }
            }

            let presentationTime = CMTime(value: frameCount, timescale: CMTimeScale(fps))
            guard pixelBufferAdaptor.append(pixelBuffer, withPresentationTime: presentationTime) else {
                let err = assetWriter.error?.localizedDescription ?? "Append failed"
                throw VideoWriterError.writerFailed(err)
            }
            frameCount += 1
        }
    }

    /// Converts a PixelImage into a 32BGRA CVPixelBuffer sized to `(targetWidth, targetHeight)`.
    private func createPixelBuffer(from image: PixelImage) -> CVPixelBuffer? {
        var pixelBuffer: CVPixelBuffer?

        if let pool = pixelBufferAdaptor.pixelBufferPool {
            CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, pool, &pixelBuffer)
        }

        if pixelBuffer == nil {
            let attrs: [CFString: Any] = [
                kCVPixelBufferCGImageCompatibilityKey: true,
                kCVPixelBufferCGBitmapContextCompatibilityKey: true
            ]
            CVPixelBufferCreate(
                kCFAllocatorDefault,
                targetWidth,
                targetHeight,
                kCVPixelFormatType_32BGRA,
                attrs as CFDictionary,
                &pixelBuffer
            )
        }

        guard let buffer = pixelBuffer else { return nil }

        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let bytesPerRow = CVPixelBufferGetBytesPerRow(buffer)

        let srcW = image.width
        let srcH = image.height
        let ch = image.channels

        let dstPtr = baseAddress.assumingMemoryBound(to: UInt8.self)

        if srcW == targetWidth && srcH == targetHeight {
            // Direct 1:1 conversion
            for y in 0..<targetHeight {
                let rowDst = dstPtr + y * bytesPerRow
                let rowSrcOffset = y * srcW * ch
                for x in 0..<targetWidth {
                    let srcIdx = rowSrcOffset + x * ch
                    let dstIdx = x * 4
                    if ch >= 3 {
                        let r = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                        let g = UInt8(min(255.0, max(0.0, image.data[srcIdx + 1] * 255.0)))
                        let b = UInt8(min(255.0, max(0.0, image.data[srcIdx + 2] * 255.0)))
                        rowDst[dstIdx] = b
                        rowDst[dstIdx + 1] = g
                        rowDst[dstIdx + 2] = r
                        rowDst[dstIdx + 3] = 255
                    } else {
                        let yVal = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                        rowDst[dstIdx] = yVal
                        rowDst[dstIdx + 1] = yVal
                        rowDst[dstIdx + 2] = yVal
                        rowDst[dstIdx + 3] = 255
                    }
                }
            }
        } else {
            // Bilinear sampling to fit target dimensions
            let scaleX = Double(srcW) / Double(targetWidth)
            let scaleY = Double(srcH) / Double(targetHeight)

            for dy in 0..<targetHeight {
                let sy = min(srcH - 1, Int(Double(dy) * scaleY))
                let rowDst = dstPtr + dy * bytesPerRow
                let rowSrcOffset = sy * srcW * ch

                for dx in 0..<targetWidth {
                    let sx = min(srcW - 1, Int(Double(dx) * scaleX))
                    let srcIdx = rowSrcOffset + sx * ch
                    let dstIdx = dx * 4

                    if ch >= 3 {
                        let r = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                        let g = UInt8(min(255.0, max(0.0, image.data[srcIdx + 1] * 255.0)))
                        let b = UInt8(min(255.0, max(0.0, image.data[srcIdx + 2] * 255.0)))
                        rowDst[dstIdx] = b
                        rowDst[dstIdx + 1] = g
                        rowDst[dstIdx + 2] = r
                        rowDst[dstIdx + 3] = 255
                    } else {
                        let yVal = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                        rowDst[dstIdx] = yVal
                        rowDst[dstIdx + 1] = yVal
                        rowDst[dstIdx + 2] = yVal
                        rowDst[dstIdx + 3] = 255
                    }
                }
            }
        }

        return buffer
    }

    /// Finishes video encoding and closes the file.
    public func finish() async throws -> URL {
        let alreadyFinished = lock.withLock {
            if isFinished { return true }
            isFinished = true
            return false
        }
        if alreadyFinished {
            return outputURL
        }

        writerInput.markAsFinished()

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            assetWriter.finishWriting {
                continuation.resume()
            }
        }

        if assetWriter.status == .failed {
            let reason = assetWriter.error?.localizedDescription ?? "Unknown failure"
            throw VideoWriterError.writerFailed("AssetWriter failed during finalization: \(reason)")
        }

        return outputURL
    }

    /// Cancels video encoding and removes any partial output file.
    public func cancel() {
        lock.lock()
        isFinished = true
        lock.unlock()

        assetWriter.cancelWriting()
        _ = try? FileManager.default.removeItem(at: outputURL)
    }
}
