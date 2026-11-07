import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

public enum TargetColorSpace: String, CaseIterable, Sendable {
    case sRGB
    case displayP3
    case linearSRGB

    public var cgColorSpace: CGColorSpace {
        switch self {
        case .sRGB:
            return CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()
        case .displayP3:
            return CGColorSpace(name: CGColorSpace.displayP3) ?? CGColorSpaceCreateDeviceRGB()
        case .linearSRGB:
            return CGColorSpace(name: CGColorSpace.linearSRGB) ?? CGColorSpaceCreateDeviceRGB()
        }
    }

    /// Whether this color space uses the sRGB non-linear electro-optical transfer function (gamma curve).
    public var isNonLinear: Bool {
        switch self {
        case .sRGB, .displayP3:
            return true
        case .linearSRGB:
            return false
        }
    }
}

public enum ImageWriter: Sendable {
    public static let conversionManifestFilename = ".staraligner-conversion.json"

    /// Write a PixelImage to the given URL using the format specified by `ImageFormat`.
    public static func write(
        _ image: PixelImage,
        to url: URL,
        format: ImageFormat,
        colorSpace: TargetColorSpace = .sRGB
    ) throws {
        switch format {
        case .tiff:
            try writeTIFF(image, to: url, colorSpace: colorSpace)
        case .png:
            try writePNG(image, to: url, colorSpace: colorSpace)
        case .jpg:
            try writeJPEG(image, to: url, quality: 0.95, colorSpace: colorSpace)
        }
    }

    /// Write a PixelImage to a 16-bit TIFF.
    public static func writeTIFF(
        _ image: PixelImage,
        to url: URL,
        colorSpace: TargetColorSpace = .sRGB
    ) throws {
        let data = try writeToData(image, utType: UTType.tiff, bitDepth: 16, quality: 1.0, colorSpace: colorSpace)
        try writeData(data, to: url)
    }

    /// Write a PixelImage to a 16-bit PNG.
    public static func writePNG(
        _ image: PixelImage,
        to url: URL,
        colorSpace: TargetColorSpace = .sRGB
    ) throws {
        let data = try writeToData(image, utType: UTType.png, bitDepth: 16, quality: 1.0, colorSpace: colorSpace)
        try writeData(data, to: url)
    }

    /// Write a PixelImage to an 8-bit JPEG.
    public static func writeJPEG(
        _ image: PixelImage,
        to url: URL,
        quality: Float = 0.95,
        colorSpace: TargetColorSpace = .sRGB
    ) throws {
        let data = try writeToData(image, utType: UTType.jpeg, bitDepth: 8, quality: quality, colorSpace: colorSpace)
        try writeData(data, to: url)
    }

    /// Encode a PixelImage into in-memory Data for a given `ImageFormat`.
    public static func writeToData(
        _ image: PixelImage,
        format: ImageFormat,
        quality: Float = 0.95,
        colorSpace: TargetColorSpace = .sRGB
    ) throws -> Data {
        switch format {
        case .tiff:
            return try writeToData(image, utType: UTType.tiff, bitDepth: 16, quality: 1.0, colorSpace: colorSpace)
        case .png:
            return try writeToData(image, utType: UTType.png, bitDepth: 16, quality: 1.0, colorSpace: colorSpace)
        case .jpg:
            return try writeToData(image, utType: UTType.jpeg, bitDepth: 8, quality: quality, colorSpace: colorSpace)
        }
    }

    /// Convert input image sequence per `JobConfig.conversionFormat`.
    ///
    /// If `config.conversionFormat == .none`, returns `sources` unchanged.
    /// Otherwise converts images to 16-bit TIFF or JPEG in `config.conversionOutputDirectory`
    /// (or a dedicated conversion directory beside inputs) and records `.staraligner-conversion.json`.
    public static func convertInputs(
        sources: [URL],
        config: JobConfig,
        progress: ((Double, Int, Int) -> Void)? = nil
    ) throws -> [URL] {
        guard config.conversionFormat != .none else {
            return sources
        }
        guard !sources.isEmpty else {
            return []
        }

        let destinationDirectory: URL
        if let outputDir = config.conversionOutputDirectory {
            destinationDirectory = outputDir
        } else {
            let base = sources.first?.deletingLastPathComponent() ?? config.inputDirectory
            destinationDirectory = base.appendingPathComponent(".staraligner-converted-\(UUID().uuidString)")
        }

        let fileManager = FileManager.default
        if !fileManager.fileExists(atPath: destinationDirectory.path) {
            do {
                try fileManager.createDirectory(at: destinationDirectory, withIntermediateDirectories: true)
            } catch {
                throw IOError.cannotWriteFile(destinationDirectory, reason: "Unable to create destination directory: \(error.localizedDescription)")
            }
        }

        // Clean up previously generated files if destination contains an old manifest
        cleanPriorManifest(in: destinationDirectory)

        let ext = config.conversionFormat == .jpg ? ".jpg" : ".tiff"
        var convertedURLs: [URL] = []
        var framesInfo: [[String: String]] = []
        let total = sources.count

        progress?(0.0, 0, total)

        for (index, source) in sources.enumerated() {
            let stem = String(source.deletingPathExtension().lastPathComponent.prefix(120))
            let filename = String(format: "%05d_%@%@", index, stem, ext)
            let destURL = destinationDirectory.appendingPathComponent(filename)

            // Decode image with configured RAW options
            let pixelImage = try ImageDecoder.decode(
                from: source,
                rawNoiseReduction: config.rawNoiseReduction,
                rawExposureEV: config.rawExposureEV
            )

            // Write image in requested format
            if config.conversionFormat == .jpg {
                try writeJPEG(pixelImage, to: destURL, quality: 0.95)
            } else {
                try writeTIFF(pixelImage, to: destURL)
            }

            // Preserve timestamp from source if available
            if let attrs = try? fileManager.attributesOfItem(atPath: source.path),
               let modDate = attrs[.modificationDate] as? Date {
                try? fileManager.setAttributes([.modificationDate: modDate], ofItemAtPath: destURL.path)
            }

            convertedURLs.append(destURL)
            framesInfo.append([
                "source": source.path,
                "converted": filename
            ])

            progress?(Double(index + 1) / Double(total), index + 1, total)
        }

        // Write conversion manifest
        let manifest: [String: Any] = [
            "version": 1,
            "format": config.conversionFormat.rawValue,
            "raw_exposure_ev": config.rawExposureEV,
            "raw_noise_reduction": config.rawNoiseReduction,
            "generated_files": convertedURLs.map(\.path),
            "frames": framesInfo
        ]

        let manifestURL = destinationDirectory.appendingPathComponent(conversionManifestFilename)
        if let data = try? JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted]) {
            try? data.write(to: manifestURL, options: [.atomic])
        }

        return convertedURLs
    }

    // MARK: - Color Conversion Helpers

    /// Converts a linear float sample in [0, 1] to non-linear sRGB (IEC 61966-2-1).
    @inline(__always)
    public static func linearToSRGB(_ linear: Float) -> Float {
        if linear <= 0.0031308 {
            return max(0.0, linear * 12.92)
        } else {
            return min(1.0, 1.055 * pow(linear, 1.0 / 2.4) - 0.055)
        }
    }

    // MARK: - Private Helpers

    private static func cleanPriorManifest(in directory: URL) {
        let manifestURL = directory.appendingPathComponent(conversionManifestFilename)
        guard let data = try? Data(contentsOf: manifestURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let files = json["generated_files"] as? [String] else {
            return
        }

        let fm = FileManager.default
        for path in files {
            try? fm.removeItem(atPath: path)
        }
        try? fm.removeItem(at: manifestURL)
    }

    private static func writeData(_ data: Data, to url: URL) throws {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            try data.write(to: url, options: [.atomic])
        } catch {
            throw IOError.cannotWriteFile(url, reason: error.localizedDescription)
        }
    }

    private static func writeToData(
        _ image: PixelImage,
        utType: UTType,
        bitDepth: Int,
        quality: Float,
        colorSpace: TargetColorSpace
    ) throws -> Data {
        guard image.width > 0 && image.height > 0 else {
            throw IOError.cannotEncodeImage(reason: "Invalid image dimensions: \(image.width)x\(image.height)")
        }
        guard image.channels == 1 || image.channels == 3 else {
            throw IOError.cannotEncodeImage(reason: "Unsupported channel count: \(image.channels) (expected 1 or 3)")
        }

        let cgImage: CGImage
        if bitDepth == 16 {
            cgImage = try create16BitCGImage(from: image, colorSpace: colorSpace)
        } else {
            cgImage = try create8BitCGImage(from: image, colorSpace: colorSpace)
        }

        let mutableData = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(mutableData, utType.identifier as CFString, 1, nil) else {
            throw IOError.cannotEncodeImage(reason: "Unable to create image destination for \(utType.identifier)")
        }

        var options: [CFString: Any] = [:]
        if utType == .jpeg {
            options[kCGImageDestinationLossyCompressionQuality] = quality
        }

        CGImageDestinationAddImage(dest, cgImage, options as CFDictionary)
        guard CGImageDestinationFinalize(dest) else {
            throw IOError.cannotEncodeImage(reason: "Failed to finalize image destination for \(utType.identifier)")
        }

        return mutableData as Data
    }

    private static func create16BitCGImage(
        from image: PixelImage,
        colorSpace: TargetColorSpace
    ) throws -> CGImage {
        let pixelCount = image.width * image.height
        let totalSamples = pixelCount * image.channels
        var uint16Data = [UInt16](repeating: 0, count: totalSamples)

        let isNonLinear = colorSpace.isNonLinear
        for i in 0..<totalSamples {
            let v = max(0.0, min(1.0, image.data[i]))
            let encoded = isNonLinear ? linearToSRGB(v) : v
            uint16Data[i] = UInt16(clamping: Int(round(encoded * 65535.0)))
        }

        let bitsPerComponent = 16
        let bitsPerPixel = 16 * image.channels
        let bytesPerRow = image.width * image.channels * 2

        let cs: CGColorSpace
        if image.channels == 1 {
            cs = CGColorSpaceCreateDeviceGray()
        } else {
            cs = colorSpace.cgColorSpace
        }

        let bitmapInfo = CGBitmapInfo.byteOrder16Little.rawValue | CGImageAlphaInfo.none.rawValue

        guard let provider = CGDataProvider(data: Data(bytes: &uint16Data, count: uint16Data.count * 2) as CFData) else {
            throw IOError.cannotEncodeImage(reason: "Failed to create CGDataProvider for 16-bit image.")
        }

        guard let cgImage = CGImage(
            width: image.width,
            height: image.height,
            bitsPerComponent: bitsPerComponent,
            bitsPerPixel: bitsPerPixel,
            bytesPerRow: bytesPerRow,
            space: cs,
            bitmapInfo: CGBitmapInfo(rawValue: bitmapInfo),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ) else {
            throw IOError.cannotEncodeImage(reason: "Failed to construct 16-bit CGImage.")
        }

        return cgImage
    }

    private static func create8BitCGImage(
        from image: PixelImage,
        colorSpace: TargetColorSpace
    ) throws -> CGImage {
        let pixelCount = image.width * image.height
        let totalSamples = pixelCount * image.channels
        var uint8Data = [UInt8](repeating: 0, count: totalSamples)

        let isNonLinear = colorSpace.isNonLinear
        for i in 0..<totalSamples {
            let v = max(0.0, min(1.0, image.data[i]))
            let encoded = isNonLinear ? linearToSRGB(v) : v
            uint8Data[i] = UInt8(clamping: Int(round(encoded * 255.0)))
        }

        let bitsPerComponent = 8
        let bitsPerPixel = 8 * image.channels
        let bytesPerRow = image.width * image.channels

        let cs: CGColorSpace
        if image.channels == 1 {
            cs = CGColorSpaceCreateDeviceGray()
        } else {
            cs = colorSpace.cgColorSpace
        }

        let bitmapInfo = CGImageAlphaInfo.none.rawValue

        guard let provider = CGDataProvider(data: Data(bytes: &uint8Data, count: uint8Data.count) as CFData) else {
            throw IOError.cannotEncodeImage(reason: "Failed to create CGDataProvider for 8-bit image.")
        }

        guard let cgImage = CGImage(
            width: image.width,
            height: image.height,
            bitsPerComponent: bitsPerComponent,
            bitsPerPixel: bitsPerPixel,
            bytesPerRow: bytesPerRow,
            space: cs,
            bitmapInfo: CGBitmapInfo(rawValue: bitmapInfo),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ) else {
            throw IOError.cannotEncodeImage(reason: "Failed to construct 8-bit CGImage.")
        }

        return cgImage
    }
}
