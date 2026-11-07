import Foundation
import CoreGraphics
import CoreImage
import Accelerate
import ImageIO

public final class ImageDecoder: Sendable {
    public static let shared = ImageDecoder()

    public let ciContext: CIContext
    private let linearColorSpace: CGColorSpace

    public init(ciContext: CIContext? = nil) {
        let cs = CGColorSpace(name: CGColorSpace.extendedLinearSRGB)
            ?? CGColorSpace(name: CGColorSpace.linearSRGB)
            ?? CGColorSpaceCreateDeviceRGB()
        self.linearColorSpace = cs

        if let ciContext {
            self.ciContext = ciContext
        } else {
            self.ciContext = CIContext(options: [
                .workingColorSpace: cs,
                .useSoftwareRenderer: false,
                // Frames are rendered once each; caching intermediates only grows memory.
                .cacheIntermediates: false,
            ])
        }
    }

    /// Decode any supported file to PixelImage (Float RGB linear-ish 0...1, 16-bit preserved).
    public func decode(
        from url: URL,
        rawNoiseReduction: Bool = true,
        rawExposureEV: Double = 0.0
    ) throws -> PixelImage {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        guard FileManager.default.fileExists(atPath: url.path) else {
            throw IOError.fileNotFound(url)
        }

        let ciImage = try loadCIImage(from: url, rawNoiseReduction: rawNoiseReduction, rawExposureEV: rawExposureEV, draftMode: false)
        return try renderCIImageToRGB(ciImage, sourceURL: url)
    }

    /// Decode image directly to single-channel Float Luma (0...1) for fast star detection.
    public func decodeLuma(
        from url: URL,
        rawNoiseReduction: Bool = true,
        rawExposureEV: Double = 0.0,
        maxDimension: Int? = nil
    ) throws -> PixelImage {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        guard FileManager.default.fileExists(atPath: url.path) else {
            throw IOError.fileNotFound(url)
        }

        let ciImage = try loadCIImage(from: url, rawNoiseReduction: rawNoiseReduction, rawExposureEV: rawExposureEV, draftMode: true)
        var lumaImage = try renderCIImageToLuma(ciImage, sourceURL: url)

        if let maxDimension, maxDimension > 0, max(lumaImage.width, lumaImage.height) > maxDimension {
            lumaImage = ImageDecoder.downscale(lumaImage, maxDimension: maxDimension)
        }

        return lumaImage
    }

    /// Downscale a PixelImage using Accelerate / vImage to fit within `maxDimension`.
    public static func downscale(_ image: PixelImage, maxDimension: Int) -> PixelImage {
        guard maxDimension > 0 else { return image }
        guard image.width > maxDimension || image.height > maxDimension else { return image }
        guard image.width > 0 && image.height > 0 else { return image }

        let maxDim = Double(maxDimension)
        let scale = min(maxDim / Double(image.width), maxDim / Double(image.height))
        let targetWidth = max(1, Int(round(Double(image.width) * scale)))
        let targetHeight = max(1, Int(round(Double(image.height) * scale)))

        if targetWidth == image.width && targetHeight == image.height {
            return image
        }

        if image.channels == 1 {
            var destData = [Float](repeating: 0, count: targetWidth * targetHeight)
            let success = image.data.withUnsafeBytes { srcPtr -> Bool in
                destData.withUnsafeMutableBytes { dstPtr -> Bool in
                    guard let srcBase = srcPtr.baseAddress, let dstBase = dstPtr.baseAddress else {
                        return false
                    }
                    var srcBuf = vImage_Buffer(
                        data: UnsafeMutableRawPointer(mutating: srcBase),
                        height: vImagePixelCount(image.height),
                        width: vImagePixelCount(image.width),
                        rowBytes: image.width * MemoryLayout<Float>.stride
                    )
                    var dstBuf = vImage_Buffer(
                        data: dstBase,
                        height: vImagePixelCount(targetHeight),
                        width: vImagePixelCount(targetWidth),
                        rowBytes: targetWidth * MemoryLayout<Float>.stride
                    )
                    let err = vImageScale_PlanarF(&srcBuf, &dstBuf, nil, vImage_Flags(kvImageHighQualityResampling))
                    return err == kvImageNoError
                }
            }
            if success {
                return PixelImage(width: targetWidth, height: targetHeight, channels: 1, data: destData)
            }
        } else if image.channels == 3 {
            let srcPixelCount = image.width * image.height
            var rSrc = [Float](repeating: 0, count: srcPixelCount)
            var gSrc = [Float](repeating: 0, count: srcPixelCount)
            var bSrc = [Float](repeating: 0, count: srcPixelCount)

            for i in 0..<srcPixelCount {
                rSrc[i] = image.data[i * 3 + 0]
                gSrc[i] = image.data[i * 3 + 1]
                bSrc[i] = image.data[i * 3 + 2]
            }

            let dstPixelCount = targetWidth * targetHeight
            var rDst = [Float](repeating: 0, count: dstPixelCount)
            var gDst = [Float](repeating: 0, count: dstPixelCount)
            var bDst = [Float](repeating: 0, count: dstPixelCount)

            let scalePlane: (inout [Float], inout [Float]) -> Bool = { srcPlane, dstPlane in
                srcPlane.withUnsafeMutableBytes { sPtr in
                    dstPlane.withUnsafeMutableBytes { dPtr in
                        guard let sBase = sPtr.baseAddress, let dBase = dPtr.baseAddress else { return false }
                        var sBuf = vImage_Buffer(
                            data: sBase,
                            height: vImagePixelCount(image.height),
                            width: vImagePixelCount(image.width),
                            rowBytes: image.width * MemoryLayout<Float>.stride
                        )
                        var dBuf = vImage_Buffer(
                            data: dBase,
                            height: vImagePixelCount(targetHeight),
                            width: vImagePixelCount(targetWidth),
                            rowBytes: targetWidth * MemoryLayout<Float>.stride
                        )
                        return vImageScale_PlanarF(&sBuf, &dBuf, nil, vImage_Flags(kvImageHighQualityResampling)) == kvImageNoError
                    }
                }
            }

            if scalePlane(&rSrc, &rDst) && scalePlane(&gSrc, &gDst) && scalePlane(&bSrc, &bDst) {
                var rgbDst = [Float](repeating: 0, count: dstPixelCount * 3)
                for i in 0..<dstPixelCount {
                    rgbDst[i * 3 + 0] = rDst[i]
                    rgbDst[i * 3 + 1] = gDst[i]
                    rgbDst[i * 3 + 2] = bDst[i]
                }
                return PixelImage(width: targetWidth, height: targetHeight, channels: 3, data: rgbDst)
            }
        }

        // Fallback: return unscaled image if scaling failed
        return image
    }

    // MARK: - Static Convenience

    public static func decode(
        from url: URL,
        rawNoiseReduction: Bool = true,
        rawExposureEV: Double = 0.0
    ) throws -> PixelImage {
        try shared.decode(from: url, rawNoiseReduction: rawNoiseReduction, rawExposureEV: rawExposureEV)
    }

    public static func decodeLuma(
        from url: URL,
        rawNoiseReduction: Bool = true,
        rawExposureEV: Double = 0.0,
        maxDimension: Int? = nil
    ) throws -> PixelImage {
        try shared.decodeLuma(from: url, rawNoiseReduction: rawNoiseReduction, rawExposureEV: rawExposureEV, maxDimension: maxDimension)
    }

    // MARK: - Private Helpers

    private func loadCIImage(
        from url: URL,
        rawNoiseReduction: Bool,
        rawExposureEV: Double,
        draftMode: Bool
    ) throws -> CIImage {
        if SequenceLister.isRaw(url: url) {
            if let filter = CIRAWFilter(imageURL: url) {
                filter.exposure = Float(rawExposureEV)
                if filter.isLuminanceNoiseReductionSupported {
                    filter.luminanceNoiseReductionAmount = rawNoiseReduction ? 1.0 : 0.0
                }
                if filter.isColorNoiseReductionSupported {
                    filter.colorNoiseReductionAmount = rawNoiseReduction ? 1.0 : 0.0
                }
                filter.boostAmount = 0.0 // linear response
                filter.isDraftModeEnabled = draftMode
                if let output = filter.outputImage {
                    return output
                }
            }
        }

        // Standard images or RAW fallback
        if let ciImage = CIImage(contentsOf: url, options: [.applyOrientationProperty: true]) {
            return ciImage
        }

        // ImageIO fallback
        if let source = CGImageSourceCreateWithURL(url as CFURL, nil),
           let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) {
            var image = CIImage(cgImage: cgImage)
            if let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
               let orientation = properties[kCGImagePropertyOrientation] as? Int32 {
                image = image.oriented(forExifOrientation: orientation)
            }
            return image
        }

        throw IOError.cannotDecodeImage(url, reason: "Image data could not be parsed by CoreImage or ImageIO.")
    }

    private func renderCIImageToRGB(_ ciImage: CIImage, sourceURL: URL) throws -> PixelImage {
        let extent = ciImage.extent.integral
        guard extent.width > 0 && extent.height > 0 else {
            throw IOError.cannotDecodeImage(sourceURL, reason: "Decoded image has zero or invalid dimensions.")
        }

        let width = Int(extent.width)
        let height = Int(extent.height)

        let renderImage: CIImage
        if extent.origin != .zero {
            renderImage = ciImage.transformed(by: CGAffineTransform(translationX: -extent.origin.x, y: -extent.origin.y))
        } else {
            renderImage = ciImage
        }

        var rgba = [Float](repeating: 0, count: width * height * 4)
        try rgba.withUnsafeMutableBytes { ptr in
            guard let baseAddress = ptr.baseAddress else {
                throw IOError.cannotDecodeImage(sourceURL, reason: "Memory allocation failed for RGBA buffer.")
            }
            ciContext.render(
                renderImage,
                toBitmap: baseAddress,
                rowBytes: width * 4 * MemoryLayout<Float>.stride,
                bounds: CGRect(x: 0, y: 0, width: width, height: height),
                format: .RGBAf,
                colorSpace: linearColorSpace
            )
        }

        // Compact RGBA -> RGB in place (destination index never overtakes the source),
        // avoiding a second full-resolution buffer (~150 MB for a 12 MP frame).
        let pixelCount = width * height
        rgba.withUnsafeMutableBufferPointer { buf in
            guard let p = buf.baseAddress else { return }
            for i in 0..<pixelCount {
                let s = i &* 4, d = i &* 3
                p[d] = p[s]; p[d &+ 1] = p[s &+ 1]; p[d &+ 2] = p[s &+ 2]
            }
        }
        rgba.removeLast(pixelCount)
        let rgb = rgba

        return PixelImage(width: width, height: height, channels: 3, data: rgb)
    }

    private func renderCIImageToLuma(_ ciImage: CIImage, sourceURL: URL) throws -> PixelImage {
        let extent = ciImage.extent.integral
        guard extent.width > 0 && extent.height > 0 else {
            throw IOError.cannotDecodeImage(sourceURL, reason: "Decoded image has zero or invalid dimensions.")
        }

        let width = Int(extent.width)
        let height = Int(extent.height)

        let renderImage: CIImage
        if extent.origin != .zero {
            renderImage = ciImage.transformed(by: CGAffineTransform(translationX: -extent.origin.x, y: -extent.origin.y))
        } else {
            renderImage = ciImage
        }

        // Rec.709 luma computed by Core Image into the red channel, rendered as a single
        // Float plane: 50 MB for a 12 MP frame instead of a 200 MB RGBA buffer plus a copy.
        let lumaWeights = CIVector(x: 0.2126, y: 0.7152, z: 0.0722, w: 0)
        let lumaImage = renderImage.applyingFilter("CIColorMatrix", parameters: [
            "inputRVector": lumaWeights,
            "inputGVector": CIVector(x: 0, y: 0, z: 0, w: 0),
            "inputBVector": CIVector(x: 0, y: 0, z: 0, w: 0),
            "inputAVector": CIVector(x: 0, y: 0, z: 0, w: 1),
        ])
        var luma = [Float](repeating: 0, count: width * height)
        try luma.withUnsafeMutableBytes { ptr in
            guard let baseAddress = ptr.baseAddress else {
                throw IOError.cannotDecodeImage(sourceURL, reason: "Memory allocation failed for luma buffer.")
            }
            // nil colour space: values stay in the linear working space, as before.
            ciContext.render(
                lumaImage,
                toBitmap: baseAddress,
                rowBytes: width * MemoryLayout<Float>.stride,
                bounds: CGRect(x: 0, y: 0, width: width, height: height),
                format: .Rf,
                colorSpace: nil
            )
        }

        return PixelImage(width: width, height: height, channels: 1, data: luma)
    }
}

extension PixelImage {
    /// Downscale this PixelImage to fit within `maxDimension` using Accelerate vImage.
    public func downscaled(maxDimension: Int) -> PixelImage {
        ImageDecoder.downscale(self, maxDimension: maxDimension)
    }
}
