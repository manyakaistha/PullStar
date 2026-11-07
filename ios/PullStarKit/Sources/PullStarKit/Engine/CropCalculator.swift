import Foundation
import CoreGraphics

public enum AlignmentError: LocalizedError, Sendable {
    case notEnoughExposures(String)
    case notEnoughMatches(String)
    case dimensionMismatch(String)
    case noCommonArea(String)
    case trackingFailed(String)
    case cancelled

    public var errorDescription: String? {
        switch self {
        case .notEnoughExposures(let msg): return msg
        case .notEnoughMatches(let msg): return msg
        case .dimensionMismatch(let msg): return msg
        case .noCommonArea(let msg): return msg
        case .trackingFailed(let msg): return msg
        case .cancelled: return "Operation was cancelled"
        }
    }
}

/// Calculates the common crop rectangle valid across all aligned frames.
///
/// Ports the conservative bounding-box crop from `field_crop` in `backend/engine/field_alignment.py`.
/// Accounts for both camera translation and camera roll by evaluating the displacement of all
/// four image corners under every frame's transformation matrix. Ensures dimensions are even
/// multiples of 2 for video encoder compatibility (e.g. YUV 4:2:0 chroma subsampling).
public enum CropCalculator {
    public static func calculateCrop(
        transforms: [FrameTransform],
        width: Int,
        height: Int
    ) throws -> CropRegion {
        guard width > 0, height > 0 else {
            throw AlignmentError.dimensionMismatch("Image dimensions must be positive: \(width)x\(height)")
        }

        let validTransforms = transforms.filter { !$0.skipped }
        guard !validTransforms.isEmpty else {
            // No valid transforms: return whole image with even dimensions
            let evenW = (width / 2) * 2
            let evenH = (height / 2) * 2
            return CropRegion(x: 0, y: 0, width: evenW, height: evenH)
        }

        var left = 0.0
        var top = 0.0
        var right = Double(width)
        var bottom = Double(height)

        let w = Double(width)
        let h = Double(height)
        let corners: [CGPoint] = [
            CGPoint(x: 0, y: 0),
            CGPoint(x: w, y: 0),
            CGPoint(x: w, y: h),
            CGPoint(x: 0, y: h)
        ]

        for transform in validTransforms {
            // For each corner C = (x, y), transformed position C' is:
            // x' = a*x + b*y + tx
            // y' = c*x + d*y + ty
            // displacement = C' - C
            var minDispX = Double.greatestFiniteMagnitude
            var maxDispX = -Double.greatestFiniteMagnitude
            var minDispY = Double.greatestFiniteMagnitude
            var maxDispY = -Double.greatestFiniteMagnitude

            for c in corners {
                let transformed = transform.apply(c)
                let dx = Double(transformed.x - c.x)
                let dy = Double(transformed.y - c.y)

                minDispX = min(minDispX, dx)
                maxDispX = max(maxDispX, dx)
                minDispY = min(minDispY, dy)
                maxDispY = max(maxDispY, dy)
            }

            left = max(left, maxDispX)
            top = max(top, maxDispY)
            right = min(right, w + minDispX)
            bottom = min(bottom, h + minDispY)
        }

        var x0 = Int(ceil(left)) + 2
        var y0 = Int(ceil(top)) + 2
        var x1 = Int(floor(right)) - 2
        var y1 = Int(floor(bottom)) - 2

        // Video encoders using 4:2:0 chroma require even dimensions
        x1 -= (x1 - x0) % 2
        y1 -= (y1 - y0) % 2

        if x1 <= x0 || y1 <= y0 {
            throw AlignmentError.noCommonArea("Camera movement leaves no common image area to stack.")
        }

        return CropRegion(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }
}
