import Foundation
import CoreGraphics
import Metal
import Accelerate

/// Errors that can occur during frame warping.
public enum WarpError: Error, LocalizedError, Sendable {
    case invalidDimensions(String)
    case degenerateTransform(String)
    case gpuUnavailable(String)
    case metalError(String)

    public var errorDescription: String? {
        switch self {
        case .invalidDimensions(let msg): return "Invalid dimensions: \(msg)"
        case .degenerateTransform(let msg): return "Degenerate transform: \(msg)"
        case .gpuUnavailable(let msg): return "GPU unavailable: \(msg)"
        case .metalError(let msg): return "Metal error: \(msg)"
        }
    }
}

/// Sendable wrapper for raw pointers across concurrent iterations.
private struct SendableBuffer<T>: @unchecked Sendable {
    let base: UnsafePointer<T>
}

private struct SendableMutableBuffer<T>: @unchecked Sendable {
    let base: UnsafeMutablePointer<T>
}

/// Metal uniforms matching the MSL struct layout.
struct WarpUniforms {
    var src_width: Int32
    var src_height: Int32
    var dst_width: Int32
    var dst_height: Int32
    var channels: Int32
    var crop_x: Int32
    var crop_y: Int32
    var m00: Float
    var m01: Float
    var m02: Float
    var m10: Float
    var m11: Float
    var m12: Float
}

/// Warps a `PixelImage` by `FrameTransform` into a `CropRegion` using Lanczos-4 sampling.
/// Supports runtime Metal compute with thread-safe multithreaded CPU fallback.
public final class FrameWarper: @unchecked Sendable {
    public let device: MTLDevice?
    private let commandQueue: MTLCommandQueue?
    private let pipelineState: MTLComputePipelineState?

    // Reusable buffers for GPU memory efficiency
    private let bufferLock = NSLock()
    private var sourceBuffer: MTLBuffer?
    private var outputBuffer: MTLBuffer?
    private var weightsBuffer: MTLBuffer?
    private var uniformsBuffer: MTLBuffer?

    /// Precomputed 32-phase Lanczos-4 weights (32 phases * 8 taps = 256 floats).
    public static let lanczosWeights: [Float] = {
        var table = [Float](repeating: 0, count: 32 * 8)
        for phase in 0..<32 {
            let frac = Float(phase) / 32.0
            var sum: Float = 0
            var row = [Float](repeating: 0, count: 8)
            for j in 0..<8 {
                let offset = Float(j - 3) - frac
                if abs(offset) < 1e-6 {
                    row[j] = 1.0
                } else if abs(offset) >= 4.0 {
                    row[j] = 0.0
                } else {
                    let pi_x = Float.pi * offset
                    let pi_x_4 = Float.pi * offset / 4.0
                    let sinc1 = sin(pi_x) / pi_x
                    let sinc2 = sin(pi_x_4) / pi_x_4
                    row[j] = sinc1 * sinc2
                }
                sum += row[j]
            }
            if phase == 0 {
                for j in 0..<8 {
                    table[phase * 8 + j] = (j == 3) ? 1.0 : 0.0
                }
            } else if abs(sum) > 1e-6 {
                for j in 0..<8 {
                    table[phase * 8 + j] = row[j] / sum
                }
            }
        }
        return table
    }()

    private static let metalSource = """
    #include <metal_stdlib>
    using namespace metal;

    struct WarpUniforms {
        int src_width;
        int src_height;
        int dst_width;
        int dst_height;
        int channels;
        int crop_x;
        int crop_y;
        float m00;
        float m01;
        float m02;
        float m10;
        float m11;
        float m12;
    };

    kernel void warp_lanczos4(
        device const float *source [[buffer(0)]],
        device float *output [[buffer(1)]],
        constant WarpUniforms &u [[buffer(2)]],
        constant float *weights [[buffer(3)]],
        uint2 gid [[thread_position_in_grid]]
    ) {
        if (gid.x >= (uint)u.dst_width || gid.y >= (uint)u.dst_height) {
            return;
        }

        float dest_x = float(gid.x + u.crop_x);
        float dest_y = float(gid.y + u.crop_y);

        float src_x = u.m00 * dest_x + u.m01 * dest_y + u.m02;
        float src_y = u.m10 * dest_x + u.m11 * dest_y + u.m12;

        float floor_x = floor(src_x);
        float floor_y = floor(src_y);

        int ix = (int)floor_x;
        int iy = (int)floor_y;

        int phase_x = clamp((int)round((src_x - floor_x) * 32.0f), 0, 31);
        int phase_y = clamp((int)round((src_y - floor_y) * 32.0f), 0, 31);

        int bx = ix - 3;
        int by = iy - 3;

        int ch = u.channels;
        int dst_idx = (gid.y * u.dst_width + gid.x) * ch;

        for (int c = 0; c < ch; c++) {
            float val = 0.0f;
            for (int i = 0; i < 8; i++) {
                int cur_y = by + i;
                if (cur_y >= 0 && cur_y < u.src_height) {
                    float wy = weights[phase_y * 8 + i];
                    int row_offset = cur_y * u.src_width * ch;
                    float h_val = 0.0f;
                    for (int j = 0; j < 8; j++) {
                        int cur_x = bx + j;
                        if (cur_x >= 0 && cur_x < u.src_width) {
                            float wx = weights[phase_x * 8 + j];
                            h_val += source[row_offset + cur_x * ch + c] * wx;
                        }
                    }
                    val += h_val * wy;
                }
            }
            output[dst_idx + c] = val;
        }
    }
    """

    public init(device: MTLDevice? = MTLCreateSystemDefaultDevice()) {
        self.device = device
        if let dev = device {
            self.commandQueue = dev.makeCommandQueue()
            do {
                let library = try dev.makeLibrary(source: Self.metalSource, options: nil)
                guard let function = library.makeFunction(name: "warp_lanczos4") else {
                    self.pipelineState = nil
                    return
                }
                self.pipelineState = try dev.makeComputePipelineState(function: function)
            } catch {
                self.pipelineState = nil
            }
        } else {
            self.commandQueue = nil
            self.pipelineState = nil
        }
    }

    /// Inverts the affine transformation matrix and solves for mapping from destination to source.
    /// Returns (m00, m01, m02, m10, m11, m12).
    public static func invertTransform(
        a: Double, b: Double, tx: Double,
        c: Double, d: Double, ty: Double
    ) throws -> (Float, Float, Float, Float, Float, Float) {
        let det = a * d - b * c
        if abs(det) < 1e-12 {
            throw WarpError.degenerateTransform("Determinant is near zero: \(det)")
        }
        let invDet = 1.0 / det
        let m00 = Float(d * invDet)
        let m01 = Float(-b * invDet)
        let m02 = Float((b * ty - d * tx) * invDet)
        let m10 = Float(-c * invDet)
        let m11 = Float(a * invDet)
        let m12 = Float((c * tx - a * ty) * invDet)
        return (m00, m01, m02, m10, m11, m12)
    }

    /// Warp `image` according to `transform` into the specified `crop`.
    public func warp(
        image: PixelImage,
        transform: FrameTransform,
        crop: CropRegion,
        backend: ComputeBackend = .auto
    ) throws -> PixelImage {
        guard crop.width > 0 && crop.height > 0 else {
            throw WarpError.invalidDimensions("Crop width and height must be positive")
        }
        guard image.width > 0 && image.height > 0 && image.channels > 0 else {
            throw WarpError.invalidDimensions("Source image dimensions must be positive")
        }

        // Fast path: pure integer translation
        let isIdentityLinear = abs(transform.a - 1.0) < 1e-7 &&
                               abs(transform.b) < 1e-7 &&
                               abs(transform.c) < 1e-7 &&
                               abs(transform.d - 1.0) < 1e-7
        let isIntegerShift = abs(transform.tx - round(transform.tx)) < 1e-7 &&
                             abs(transform.ty - round(transform.ty)) < 1e-7

        if isIdentityLinear && isIntegerShift {
            return warpIntegerTranslation(image: image, transform: transform, crop: crop)
        }

        // General Lanczos-4 path
        let shouldUseGPU: Bool = switch backend {
        case .cpu: false
        case .gpu: true
        case .auto:
            pipelineState != nil && (crop.width * crop.height >= 512 * 512)
        }

        if shouldUseGPU {
            if let result = try? warpGPU(image: image, transform: transform, crop: crop) {
                return result
            }
            if backend == .gpu {
                throw WarpError.gpuUnavailable("Metal GPU warp failed and CPU fallback was disallowed")
            }
        }

        return warpCPU(image: image, transform: transform, crop: crop)
    }

    // MARK: - Fast Integer Translation

    private func warpIntegerTranslation(
        image: PixelImage,
        transform: FrameTransform,
        crop: CropRegion
    ) -> PixelImage {
        let itx = Int(round(transform.tx))
        let ity = Int(round(transform.ty))

        var output = PixelImage(width: crop.width, height: crop.height, channels: image.channels)

        let srcX0 = crop.x - itx
        let srcX1 = crop.x + crop.width - itx
        let srcY0 = crop.y - ity
        let srcY1 = crop.y + crop.height - ity

        let dstX0 = max(0, -srcX0)
        let dstY0 = max(0, -srcY0)
        let dstX1 = crop.width - max(0, srcX1 - image.width)
        let dstY1 = crop.height - max(0, srcY1 - image.height)

        let validSrcX0 = max(0, srcX0)
        let validSrcY0 = max(0, srcY0)
        let validSrcX1 = min(image.width, srcX1)
        let validSrcY1 = min(image.height, srcY1)

        guard validSrcX1 > validSrcX0 && validSrcY1 > validSrcY0 && dstX1 > dstX0 && dstY1 > dstY0 else {
            return output
        }

        let copyWidth = dstX1 - dstX0
        let ch = image.channels
        let bytesPerPixelRow = copyWidth * ch * MemoryLayout<Float>.stride

        image.data.withUnsafeBufferPointer { srcBuf in
            guard let srcBase = srcBuf.baseAddress else { return }
            output.data.withUnsafeMutableBufferPointer { dstBuf in
                guard let dstBase = dstBuf.baseAddress else { return }

                for row in 0..<(dstY1 - dstY0) {
                    let sy = validSrcY0 + row
                    let dy = dstY0 + row
                    let srcOffset = (sy * image.width + validSrcX0) * ch
                    let dstOffset = (dy * crop.width + dstX0) * ch
                    memcpy(dstBase + dstOffset, srcBase + srcOffset, bytesPerPixelRow)
                }
            }
        }

        return output
    }

    // MARK: - CPU Lanczos-4 Warper

    public func warpCPU(
        image: PixelImage,
        transform: FrameTransform,
        crop: CropRegion
    ) -> PixelImage {
        guard let (m00, m01, m02, m10, m11, m12) = try? Self.invertTransform(
            a: transform.a, b: transform.b, tx: transform.tx,
            c: transform.c, d: transform.d, ty: transform.ty
        ) else {
            return PixelImage(width: crop.width, height: crop.height, channels: image.channels)
        }

        var output = PixelImage(width: crop.width, height: crop.height, channels: image.channels)
        let weights = Self.lanczosWeights
        let srcW = image.width
        let srcH = image.height
        let dstW = crop.width
        let dstH = crop.height
        let ch = image.channels
        let cropX = crop.x
        let cropY = crop.y

        image.data.withUnsafeBufferPointer { srcBuf in
            guard let srcBase = srcBuf.baseAddress else { return }
            output.data.withUnsafeMutableBufferPointer { dstBuf in
                guard let dstBase = dstBuf.baseAddress else { return }

                let sendableSrc = SendableBuffer(base: srcBase)
                let sendableDst = SendableMutableBuffer(base: dstBase)

                DispatchQueue.concurrentPerform(iterations: dstH) { y in
                    let destY = Float(y + cropY)
                    for x in 0..<dstW {
                        let destX = Float(x + cropX)
                        let srcX = m00 * destX + m01 * destY + m02
                        let srcY = m10 * destX + m11 * destY + m12

                        let floorX = floor(srcX)
                        let floorY = floor(srcY)
                        let ix = Int(floorX)
                        let iy = Int(floorY)

                        let phaseX = max(0, min(31, Int(round((srcX - floorX) * 32.0))))
                        let phaseY = max(0, min(31, Int(round((srcY - floorY) * 32.0))))

                        let bx = ix - 3
                        let by = iy - 3
                        let dstIdx = (y * dstW + x) * ch

                        for c in 0..<ch {
                            var val: Float = 0
                            for i in 0..<8 {
                                let curY = by + i
                                if curY >= 0 && curY < srcH {
                                    let wy = weights[phaseY * 8 + i]
                                    let rowOffset = curY * srcW * ch
                                    var hVal: Float = 0
                                    for j in 0..<8 {
                                        let curX = bx + j
                                        if curX >= 0 && curX < srcW {
                                            let wx = weights[phaseX * 8 + j]
                                            hVal += sendableSrc.base[rowOffset + curX * ch + c] * wx
                                        }
                                    }
                                    val += hVal * wy
                                }
                            }
                            sendableDst.base[dstIdx + c] = val
                        }
                    }
                }
            }
        }

        return output
    }

    // MARK: - Metal GPU Lanczos-4 Warper

    private func warpGPU(
        image: PixelImage,
        transform: FrameTransform,
        crop: CropRegion
    ) throws -> PixelImage {
        guard let device = device,
              let commandQueue = commandQueue,
              let pipelineState = pipelineState else {
            throw WarpError.gpuUnavailable("Metal pipeline not initialized")
        }

        let (m00, m01, m02, m10, m11, m12) = try Self.invertTransform(
            a: transform.a, b: transform.b, tx: transform.tx,
            c: transform.c, d: transform.d, ty: transform.ty
        )

        var uniforms = WarpUniforms(
            src_width: Int32(image.width),
            src_height: Int32(image.height),
            dst_width: Int32(crop.width),
            dst_height: Int32(crop.height),
            channels: Int32(image.channels),
            crop_x: Int32(crop.x),
            crop_y: Int32(crop.y),
            m00: m00, m01: m01, m02: m02,
            m10: m10, m11: m11, m12: m12
        )

        let srcByteCount = image.data.count * MemoryLayout<Float>.stride
        let dstByteCount = crop.width * crop.height * image.channels * MemoryLayout<Float>.stride

        bufferLock.lock()
        defer { bufferLock.unlock() }

        // Reuse or allocate source buffer
        let srcBuffer: MTLBuffer
        if let existing = sourceBuffer, existing.length >= srcByteCount {
            srcBuffer = existing
        } else {
            guard let newBuf = device.makeBuffer(length: srcByteCount, options: .storageModeShared) else {
                throw WarpError.metalError("Failed to allocate source buffer")
            }
            sourceBuffer = newBuf
            srcBuffer = newBuf
        }
        memcpy(srcBuffer.contents(), image.data, srcByteCount)

        // Reuse or allocate output buffer
        let dstBuffer: MTLBuffer
        if let existing = outputBuffer, existing.length >= dstByteCount {
            dstBuffer = existing
        } else {
            guard let newBuf = device.makeBuffer(length: dstByteCount, options: .storageModeShared) else {
                throw WarpError.metalError("Failed to allocate destination buffer")
            }
            outputBuffer = newBuf
            dstBuffer = newBuf
        }

        // Reuse or allocate weights buffer
        let wBuffer: MTLBuffer
        let wByteCount = Self.lanczosWeights.count * MemoryLayout<Float>.stride
        if let existing = weightsBuffer {
            wBuffer = existing
        } else {
            guard let newBuf = device.makeBuffer(bytes: Self.lanczosWeights, length: wByteCount, options: .storageModeShared) else {
                throw WarpError.metalError("Failed to allocate weights buffer")
            }
            weightsBuffer = newBuf
            wBuffer = newBuf
        }

        // Reuse or allocate uniforms buffer
        let uBuffer: MTLBuffer
        let uByteCount = MemoryLayout<WarpUniforms>.stride
        if let existing = uniformsBuffer {
            uBuffer = existing
        } else {
            guard let newBuf = device.makeBuffer(length: uByteCount, options: .storageModeShared) else {
                throw WarpError.metalError("Failed to allocate uniforms buffer")
            }
            uniformsBuffer = newBuf
            uBuffer = newBuf
        }
        memcpy(uBuffer.contents(), &uniforms, uByteCount)

        guard let commandBuffer = commandQueue.makeCommandBuffer(),
              let encoder = commandBuffer.makeComputeCommandEncoder() else {
            throw WarpError.metalError("Failed to create command encoder")
        }

        encoder.setComputePipelineState(pipelineState)
        encoder.setBuffer(srcBuffer, offset: 0, index: 0)
        encoder.setBuffer(dstBuffer, offset: 0, index: 1)
        encoder.setBuffer(uBuffer, offset: 0, index: 2)
        encoder.setBuffer(wBuffer, offset: 0, index: 3)

        let threadgroupSize = MTLSize(width: 16, height: 16, depth: 1)

        encoder.dispatchThreads(
            MTLSize(width: crop.width, height: crop.height, depth: 1),
            threadsPerThreadgroup: threadgroupSize
        )
        encoder.endEncoding()

        commandBuffer.commit()
        commandBuffer.waitUntilCompleted()

        if let error = commandBuffer.error {
            throw WarpError.metalError("GPU command execution failed: \(error.localizedDescription)")
        }

        var output = PixelImage(width: crop.width, height: crop.height, channels: image.channels)
        output.data.withUnsafeMutableBufferPointer { dstPtr in
            guard let base = dstPtr.baseAddress else { return }
            memcpy(base, dstBuffer.contents(), dstByteCount)
        }

        return output
    }
}
