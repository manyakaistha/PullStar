import Foundation
import CoreGraphics
import CoreImage
import ImageIO
import UniformTypeIdentifiers

public enum PreviewRenderer: Sendable {
    private static let sRGBColorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()

    /// Generate an orientation-correct JPEG preview of the image at `url`, constrained to `maxDimension`.
    public static func renderPreview(of url: URL, maxDimension: Int) throws -> Data {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        guard FileManager.default.fileExists(atPath: url.path) else {
            throw IOError.fileNotFound(url)
        }

        let maxDim = max(1, maxDimension)

        // 1. Try ImageIO thumbnail extraction (very fast and reads camera-embedded preview / applies transform)
        if let source = CGImageSourceCreateWithURL(url as CFURL, nil) {
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceThumbnailMaxPixelSize: maxDim
            ]
            if let thumb = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) {
                if let jpegData = encodeCGImageToJPEG(thumb, quality: 0.95) {
                    return jpegData
                }
            }
        }

        // 2. If RAW, try CIRAWFilter with scaleFactor and draft mode
        if SequenceLister.isRaw(url: url) {
            if let filter = CIRAWFilter(imageURL: url) {
                let native = filter.nativeSize
                let maxSide = max(native.width, native.height)
                if maxSide > 0 {
                    filter.scaleFactor = min(1.0, Float(maxDim) / Float(maxSide))
                }
                filter.isDraftModeEnabled = true
                if let output = filter.outputImage {
                    let context = ImageDecoder.shared.ciContext
                    if let data = context.jpegRepresentation(
                        of: output,
                        colorSpace: sRGBColorSpace,
                        options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.95]
                    ) {
                        return data
                    }
                }
            }
        }

        // 3. Fallback to CIImage with orientation
        if let ciImage = CIImage(contentsOf: url, options: [.applyOrientationProperty: true]) {
            let extent = ciImage.extent.integral
            guard extent.width > 0 && extent.height > 0 else {
                throw IOError.cannotDecodeImage(url, reason: "Image extent is empty.")
            }

            let maxSide = max(extent.width, extent.height)
            let scale = maxSide > Double(maxDim) ? Double(maxDim) / maxSide : 1.0

            var outputImage = ciImage
            if scale < 1.0 {
                outputImage = ciImage.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            }
            if outputImage.extent.origin != .zero {
                outputImage = outputImage.transformed(
                    by: CGAffineTransform(translationX: -outputImage.extent.origin.x, y: -outputImage.extent.origin.y)
                )
            }

            let context = ImageDecoder.shared.ciContext
            if let data = context.jpegRepresentation(
                of: outputImage,
                colorSpace: sRGBColorSpace,
                options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.95]
            ) {
                return data
            }
        }

        throw IOError.cannotDecodeImage(url, reason: "Unable to create preview for \(url.lastPathComponent)")
    }

    /// Asynchronous wrapper for `renderPreview`.
    public static func renderPreview(of url: URL, maxDimension: Int) async throws -> Data {
        let syncFunc: (URL, Int) throws -> Data = renderPreview(of:maxDimension:)
        return try syncFunc(url, maxDimension)
    }

    private static func encodeCGImageToJPEG(_ cgImage: CGImage, quality: Float) -> Data? {
        let mutableData = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(mutableData, UTType.jpeg.identifier as CFString, 1, nil) else {
            return nil
        }
        let options: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: quality
        ]
        CGImageDestinationAddImage(dest, cgImage, options as CFDictionary)
        guard CGImageDestinationFinalize(dest) else {
            return nil
        }
        return mutableData as Data
    }
}
