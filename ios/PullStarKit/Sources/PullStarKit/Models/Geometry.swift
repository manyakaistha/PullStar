import Foundation
import CoreGraphics

/// 2x3 similarity/affine transform mapping source pixel coords -> reference coords:
/// x' = a*x + b*y + tx ; y' = c*x + d*y + ty. (Pixel coords, origin top-left.)
public struct FrameTransform: Sendable, Equatable, Codable {
    public var a = 1.0, b = 0.0, tx = 0.0
    public var c = 0.0, d = 1.0, ty = 0.0
    public var frameIndex = 0
    public var time = 0.0            // seconds since first frame
    public var skipped = false       // frame could not be aligned
    public init() {}
    public func apply(_ p: CGPoint) -> CGPoint { CGPoint(x: a * p.x + b * p.y + tx, y: c * p.x + d * p.y + ty) }
}

/// Common crop (pixel rect in reference frame) valid for all aligned frames.
public struct CropRegion: Sendable, Equatable, Codable {
    public var x = 0, y = 0, width = 0, height = 0
    public init(x: Int = 0, y: Int = 0, width: Int = 0, height: Int = 0) { self.x = x; self.y = y; self.width = width; self.height = height }
}

/// Floating point RGB(A) planar-interleaved image, linear 0...1, the engine's working pixel format.
public struct PixelImage: Sendable {
    public var width: Int
    public var height: Int
    public var channels: Int           // 3 (RGB) or 1 (luma)
    public var data: [Float]           // row-major, interleaved
    public init(width: Int, height: Int, channels: Int, data: [Float]) { self.width = width; self.height = height; self.channels = channels; self.data = data }
    public init(width: Int, height: Int, channels: Int) { self.init(width: width, height: height, channels: channels, data: [Float](repeating: 0, count: width * height * channels)) }
}
