import Foundation
import CoreGraphics
import ImageIO

/// Metadata manifest written alongside aligned frame exports.
public struct FrameExportManifest: Codable, Sendable {
    public var format: String
    public var files: [String]
    public var source_files: [String]
    public var sky_motion_preserved: Bool
    public var crop: CropSize
    public var skipped_frames: Int

    public struct CropSize: Codable, Sendable {
        public var width: Int
        public var height: Int
    }
}

/// Exports aligned individual frames to disk and writes a `sequence.json` manifest.
public final class AlignedFrameExporter: @unchecked Sendable {
    public let destinationDirectory: URL
    public let format: ImageFormat
    public let crop: CropRegion
    private let lock = NSLock()
    private var exportedFilenames: [String] = []
    private var sourceFilenames: [String] = []

    public init(
        destinationDirectory: URL,
        format: ImageFormat = .tiff,
        crop: CropRegion
    ) {
        self.destinationDirectory = destinationDirectory
        self.format = format
        self.crop = crop
    }

    /// Prepares the output directory, ensuring it is clean.
    public func prepare() throws {
        try FileManager.default.createDirectory(at: destinationDirectory, withIntermediateDirectories: true)
    }

    /// Exports a single aligned frame to the destination directory.
    @discardableResult
    public func exportFrame(
        _ image: PixelImage,
        index: Int,
        originalName: String? = nil
    ) throws -> URL {
        try prepare()

        let ext = switch format {
        case .tiff: "tiff"
        case .png: "png"
        case .jpg: "jpg"
        }

        let stem = originalName ?? "frame"
        let filename = String(format: "%05d_%@.%@", index, stem, ext)
        let fileURL = destinationDirectory.appendingPathComponent(filename)

        guard let data = encodeImage(image, format: format) else {
            throw VideoWriterError.writerFailed("Failed to encode frame \(index) as \(format)")
        }

        try data.write(to: fileURL, options: .atomic)

        lock.lock()
        exportedFilenames.append(filename)
        sourceFilenames.append(stem)
        lock.unlock()

        return fileURL
    }

    /// Writes the final `sequence.json` manifest into the export directory.
    public func writeManifest(skippedFrames: Int = 0) throws -> URL {
        lock.lock()
        let files = exportedFilenames
        let sources = sourceFilenames
        lock.unlock()

        let manifest = FrameExportManifest(
            format: format.rawValue,
            files: files,
            source_files: sources,
            sky_motion_preserved: true,
            crop: .init(width: crop.width, height: crop.height),
            skipped_frames: skippedFrames
        )

        let manifestURL = destinationDirectory.appendingPathComponent("sequence.json")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(manifest)
        try data.write(to: manifestURL, options: .atomic)
        return manifestURL
    }

    // MARK: - Image Encoding

    private func encodeImage(_ image: PixelImage, format: ImageFormat) -> Data? {
        let w = image.width
        let h = image.height
        let ch = image.channels
        guard w > 0 && h > 0 && !image.data.isEmpty else { return nil }

        var rgbBytes = [UInt8](repeating: 0, count: w * h * 3)
        for i in 0..<(w * h) {
            let srcIdx = i * ch
            let dstIdx = i * 3
            if ch >= 3 {
                rgbBytes[dstIdx] = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                rgbBytes[dstIdx + 1] = UInt8(min(255.0, max(0.0, image.data[srcIdx + 1] * 255.0)))
                rgbBytes[dstIdx + 2] = UInt8(min(255.0, max(0.0, image.data[srcIdx + 2] * 255.0)))
            } else {
                let val = UInt8(min(255.0, max(0.0, image.data[srcIdx] * 255.0)))
                rgbBytes[dstIdx] = val
                rgbBytes[dstIdx + 1] = val
                rgbBytes[dstIdx + 2] = val
            }
        }

        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue)

        guard let provider = CGDataProvider(data: Data(rgbBytes) as CFData),
              let cgImage = CGImage(
                width: w,
                height: h,
                bitsPerComponent: 8,
                bitsPerPixel: 24,
                bytesPerRow: w * 3,
                space: colorSpace,
                bitmapInfo: bitmapInfo,
                provider: provider,
                decode: nil,
                shouldInterpolate: true,
                intent: .defaultIntent
              ) else {
            return nil
        }

        let uti: CFString = switch format {
        case .tiff: "public.tiff" as CFString
        case .png: "public.png" as CFString
        case .jpg: "public.jpeg" as CFString
        }

        let outputData = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            outputData as CFMutableData,
            uti,
            1,
            nil
        ) else {
            return nil
        }

        var options: [CFString: Any] = [:]
        if format == .jpg {
            options[kCGImageDestinationLossyCompressionQuality] = 0.95
        }

        CGImageDestinationAddImage(destination, cgImage, options as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }

        return outputData as Data
    }
}
