import Foundation
import CoreGraphics

/// Result produced by `StackPipeline.run`.
public struct StackPipelineResult: Sendable {
    public var finalImage: PixelImage?
    public var videoURL: URL?
    public var exportedFrameURLs: [URL]
    public var livePreviewRevision: Int
    public var totalStepsProcessed: Int

    public init(
        finalImage: PixelImage? = nil,
        videoURL: URL? = nil,
        exportedFrameURLs: [URL] = [],
        livePreviewRevision: Int = 0,
        totalStepsProcessed: Int = 0
    ) {
        self.finalImage = finalImage
        self.videoURL = videoURL
        self.exportedFrameURLs = exportedFrameURLs
        self.livePreviewRevision = livePreviewRevision
        self.totalStepsProcessed = totalStepsProcessed
    }
}

/// Orchestrates pass-2 alignment, stacking, trail extension, video recording, and frame exports.
public enum StackPipeline {
    /// Runs pass 2 over `frameCount` frames using provided transforms and crop region.
    /// Fully cancellation-aware via standard Swift concurrency.
    public static func run(
        frameCount: Int,
        transforms: [FrameTransform],
        crop: CropRegion,
        config: JobConfig,
        loadFrame: @Sendable (Int) async throws -> PixelImage,
        progress: (@Sendable (JobState) -> Void)? = nil,
        onFrameWarped: (@Sendable (Int, PixelImage) async throws -> Void)? = nil,
        onFinalImage: (@Sendable (PixelImage) async throws -> Void)? = nil
    ) async throws -> StackPipelineResult {
        try Task.checkCancellation()

        guard frameCount > 0 else {
            throw WarpError.invalidDimensions("Frame count must be greater than zero")
        }
        guard crop.width > 0 && crop.height > 0 else {
            throw WarpError.invalidDimensions("Crop dimensions must be positive")
        }

        var state = JobState()
        state.stage = .pass2
        state.status = .running
        state.current = 0
        state.total = frameCount
        state.progress = 0.0
        progress?(state)

        let warper = FrameWarper()

        let blendMode: TrailBlendMode = (config.blendMode == "add") ? .add : .lighten
        let stacker = TrailStacker(
            width: crop.width,
            height: crop.height,
            channels: 3,
            blendMode: blendMode
        )

        // Checkpoint setup
        let checkpointDir = config.outputDirectory.appendingPathComponent(".pullstar_checkpoints")
        var startFrame = 0
        if config.useCheckpoint && config.resume {
            if let resumed = stacker.resumeCheckpoint(from: checkpointDir, config: config) {
                startFrame = min(frameCount, resumed + 1)
            }
        }

        // Video writer setup
        var videoWriter: TrailVideoWriter? = nil
        if config.videoEnabled && !config.noStack {
            let baseVideoURL = config.outputDirectory.appendingPathComponent(config.outputBaseName)
            videoWriter = try TrailVideoWriter(
                destinationURL: baseVideoURL,
                sourceWidth: crop.width,
                sourceHeight: crop.height,
                fps: config.videoFPS,
                quality: config.quality,
                format: config.videoFormat,
                resolution: config.videoResolution
            )
        }

        // Frame exporter setup
        var frameExporter: AlignedFrameExporter? = nil
        var exportedURLs: [URL] = []
        if config.saveFrames {
            let framesFolder = config.noStack
                ? config.outputDirectory
                : config.outputDirectory.appendingPathComponent("\(config.outputBaseName)_frames")
            let exporter = AlignedFrameExporter(
                destinationDirectory: framesFolder,
                format: config.imageFormat,
                crop: crop
            )
            try exporter.prepare()
            frameExporter = exporter
        }

        // Live preview publisher setup
        let previewURL = config.outputDirectory.appendingPathComponent("\(config.outputBaseName).live.jpg")
        let previewPublisher = LivePreviewPublisher(destinationURL: previewURL) { [state] _, rev in
            var updated = state
            updated.livePreviewURL = previewURL
            updated.livePreviewRevision = rev
            progress?(updated)
        }

        // Calculate rotation angles for trail extension
        var rotationAngles: [Double] = []
        if config.extensionFactor > 1.0 {
            let earthRateDegreesPerSec = 360.0 / 86164.0 // ~0.004178 deg/sec
            let hasValidTimes = transforms.count >= 2 && transforms.last!.time > transforms.first!.time
            if hasValidTimes {
                let startTime = transforms.first!.time
                for t in transforms {
                    let deltaSec = t.time - startTime
                    rotationAngles.append(deltaSec * earthRateDegreesPerSec)
                }
            } else {
                for i in 0..<frameCount {
                    rotationAngles.append(Double(i) * 0.125)
                }
            }
        }

        let polarisCenter: CGPoint = {
            if let p = config.polaris {
                return CGPoint(x: p.x - CGFloat(crop.x), y: p.y - CGFloat(crop.y))
            }
            return CGPoint(x: CGFloat(crop.width) / 2.0, y: CGFloat(crop.height) / 2.0)
        }()

        var lastAlignedFrame: PixelImage? = nil
        var stepsProcessed = 0

        // =====================================================================
        // REAL FRAMES PROCESSING LOOP
        // =====================================================================
        for i in startFrame..<frameCount {
            try Task.checkCancellation()

            let rawImage = try await loadFrame(i)
            let transform = (i < transforms.count) ? transforms[i] : FrameTransform()

            if transform.skipped {
                continue
            }

            let aligned = try warper.warp(
                image: rawImage,
                transform: transform,
                crop: crop,
                backend: config.computeBackend
            )
            lastAlignedFrame = aligned

            try await onFrameWarped?(i, aligned)

            if let exporter = frameExporter {
                let url = try exporter.exportFrame(aligned, index: i)
                exportedURLs.append(url)
            }

            if config.useForegroundMask && stacker.skyMask == nil {
                stacker.computeSkyMask(from: aligned)
            }

            if !config.noStack {
                stacker.blend(frame: aligned, isSynthetic: false)

                // Video snapshot for real frame
                if let writer = videoWriter {
                    let repeats = (config.videoHyperlapse || config.extensionFactor > 1.0)
                        ? 1
                        : config.videoSlowdown
                    try writer.writeSnapshot(image: stacker.accumulator, repeats: repeats)
                }

                // Synthetic ghost frames between frame i and frame i + 1
                if config.extensionFactor > 1.0 && i < frameCount - 1 && rotationAngles.count > i + 1 {
                    let angleDelta = rotationAngles[i + 1] - rotationAngles[i]
                    let numGhosts = max(1, Int(Double(config.ghostFramesPerReal) * (config.extensionFactor - 1.0)))

                    let selectedVideoGhosts = Set(TrailEffects.evenlySpaced(
                        Array(0..<numGhosts),
                        count: max(0, config.videoSlowdown - 1)
                    ))

                    for g in 0..<numGhosts {
                        try Task.checkCancellation()
                        let alpha = Double(g + 1) / Double(numGhosts + 1)
                        let ghostAngle = alpha * angleDelta

                        if !TrailEffects.withinTailAngle(angleDegrees: ghostAngle, thresholdDegrees: config.tailAngleThreshold) {
                            continue
                        }

                        let tailOpacity = TrailEffects.tailOpacity(
                            angleDegrees: ghostAngle,
                            spanDegrees: config.tailAngleThreshold > 0 ? config.tailAngleThreshold : abs(angleDelta),
                            taperStrength: config.tailTaperStrength
                        )
                        let fade = Float((1.0 - alpha * config.syntheticFadeFactor) * tailOpacity)

                        // Rotate aligned frame around polaris
                        let rotTransform = makeRotationTransform(
                            center: polarisCenter,
                            angleDegrees: ghostAngle
                        )
                        let ghost = try warper.warp(
                            image: aligned,
                            transform: rotTransform,
                            crop: CropRegion(x: 0, y: 0, width: crop.width, height: crop.height),
                            backend: config.computeBackend
                        )

                        stacker.blend(
                            frame: ghost,
                            isSynthetic: true,
                            fade: fade,
                            useMask: config.useForegroundMask
                        )

                        if let writer = videoWriter, !config.videoHyperlapse, selectedVideoGhosts.contains(g) {
                            try writer.writeSnapshot(image: stacker.accumulator, repeats: 1)
                        }
                    }
                }

                // Gap filling
                if config.fillGaps && i < frameCount - 1 && i < transforms.count - 1 {
                    let t0 = transforms[i].time
                    let t1 = transforms[i + 1].time
                    let interval = t1 - t0
                    if interval > 1.5 {
                        let missingCount = max(1, Int(round(interval)) - 1)
                        for k in 1...missingCount {
                            try Task.checkCancellation()
                            let alpha = Double(k) / Double(missingCount + 1)
                            let interpTransform = interpolateTransform(from: transforms[i], to: transforms[i + 1], alpha: alpha)
                            let interpFrame = try warper.warp(
                                image: rawImage,
                                transform: interpTransform,
                                crop: crop,
                                backend: config.computeBackend
                            )
                            let fade = Float(1.0 - config.syntheticFadeFactor)
                            stacker.blend(frame: interpFrame, isSynthetic: true, fade: fade, useMask: config.useForegroundMask)
                        }
                    }
                }

                previewPublisher.publish(accumulator: stacker.accumulator)

                if config.useCheckpoint && (i + 1) % 10 == 0 {
                    try? stacker.saveCheckpoint(to: checkpointDir, frameIndex: i, config: config)
                }
            }

            stepsProcessed += 1
            state.current = stepsProcessed
            state.progress = Double(stepsProcessed) / Double(frameCount)
            progress?(state)
        }

        // =====================================================================
        // SYNTHETIC FUTURE EXTRAPOLATION
        // =====================================================================
        if config.extensionFactor > 1.0 && !config.noStack, let lastAligned = lastAlignedFrame {
            try Task.checkCancellation()

            let targetTotal = Int(Double(frameCount) * config.extensionFactor)
            let extensionFrames = max(0, targetTotal - frameCount)

            if extensionFrames > 0 {
                let rotSpeed: Double = {
                    if rotationAngles.count >= 2 {
                        var deltas: [Double] = []
                        for idx in 1..<rotationAngles.count {
                            deltas.append(rotationAngles[idx] - rotationAngles[idx - 1])
                        }
                        deltas.sort()
                        return deltas[deltas.count / 2]
                    }
                    return 0.125
                }()

                let selectedExtension = Set(TrailEffects.evenlySpaced(
                    Array(0..<extensionFrames),
                    count: config.videoSlowdown * max(1, frameCount - 1)
                ))

                let tailSpan = Double(extensionFrames) * rotSpeed

                for k in 0..<extensionFrames {
                    try Task.checkCancellation()
                    let angleOffset = Double(k + 1) * rotSpeed

                    if !TrailEffects.withinTailAngle(angleDegrees: angleOffset, thresholdDegrees: config.tailAngleThreshold) {
                        break
                    }

                    let tailOpacity = TrailEffects.tailOpacity(
                        angleDegrees: angleOffset,
                        spanDegrees: tailSpan,
                        taperStrength: config.tailTaperStrength
                    )
                    let fade = Float(tailOpacity)

                    let rotTransform = makeRotationTransform(
                        center: polarisCenter,
                        angleDegrees: angleOffset
                    )
                    let extrapolated = try warper.warp(
                        image: lastAligned,
                        transform: rotTransform,
                        crop: CropRegion(x: 0, y: 0, width: crop.width, height: crop.height),
                        backend: config.computeBackend
                    )

                    stacker.blend(
                        frame: extrapolated,
                        isSynthetic: true,
                        fade: fade,
                        useMask: config.useForegroundMask
                    )

                    if let writer = videoWriter, !config.videoHyperlapse, selectedExtension.contains(k) {
                        try writer.writeSnapshot(image: stacker.accumulator, repeats: 1)
                    }

                    previewPublisher.publish(accumulator: stacker.accumulator)
                }
            }
        }

        // =====================================================================
        // FINALIZATION
        // =====================================================================
        try Task.checkCancellation()

        var videoFinalURL: URL? = nil
        if let writer = videoWriter {
            state.stage = .videoRender
            progress?(state)
            videoFinalURL = try await writer.finish()
        }

        if let exporter = frameExporter {
            _ = try? exporter.writeManifest()
        }

        // Clean up checkpoints on success
        if config.useCheckpoint {
            try? FileManager.default.removeItem(at: checkpointDir)
        }

        let finalImage: PixelImage? = (!config.noStack) ? stacker.currentSnapshot() : nil
        if let final = finalImage {
            previewPublisher.publish(accumulator: final, force: true)
            try await onFinalImage?(final)
        }

        state.stage = .done
        state.status = .completed
        state.progress = 1.0
        state.resultURL = videoFinalURL ?? config.outputDirectory
        state.videoURL = videoFinalURL
        progress?(state)

        return StackPipelineResult(
            finalImage: finalImage,
            videoURL: videoFinalURL,
            exportedFrameURLs: exportedURLs,
            livePreviewRevision: previewPublisher.revision,
            totalStepsProcessed: stepsProcessed
        )
    }

    // MARK: - Internal Helpers

    /// Constructs an affine rotation transform around `center` by `angleDegrees`.
    public static func makeRotationTransform(
        center: CGPoint,
        angleDegrees: Double
    ) -> FrameTransform {
        let radians = angleDegrees * .pi / 180.0
        let cosA = cos(radians)
        let sinA = sin(radians)
        let cx = Double(center.x)
        let cy = Double(center.y)

        var t = FrameTransform()
        t.a = cosA
        t.b = -sinA
        t.tx = (1.0 - cosA) * cx + sinA * cy
        t.c = sinA
        t.d = cosA
        t.ty = -sinA * cx + (1.0 - cosA) * cy
        return t
    }

    /// Linearly interpolates two FrameTransforms.
    public static func interpolateTransform(
        from t0: FrameTransform,
        to t1: FrameTransform,
        alpha: Double
    ) -> FrameTransform {
        var t = FrameTransform()
        t.a = t0.a + alpha * (t1.a - t0.a)
        t.b = t0.b + alpha * (t1.b - t0.b)
        t.tx = t0.tx + alpha * (t1.tx - t0.tx)
        t.c = t0.c + alpha * (t1.c - t0.c)
        t.d = t0.d + alpha * (t1.d - t0.d)
        t.ty = t0.ty + alpha * (t1.ty - t0.ty)
        t.time = t0.time + alpha * (t1.time - t0.time)
        return t
    }
}
