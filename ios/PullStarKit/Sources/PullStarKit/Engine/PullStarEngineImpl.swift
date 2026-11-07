import Foundation
import CoreGraphics
#if canImport(Metal)
import Metal
#endif

/// Production implementation of `PullStarEngine`.
///
/// Drives the full lifecycle:
/// `preparation` → `conversion` (optional) → `pass1` (analysis & tracking) → `cropCalc` →
/// `pass2` (warping, stacking, live preview, trail extrapolation) → `videoRender` (optional) → `done`.
public final class PullStarEngineImpl: PullStarEngine, @unchecked Sendable {

    public init() {}

    // MARK: - PullStarEngine Protocol Methods

    /// Enumerate supported images in a folder, sorted per `sortByTime`.
    public func listSequence(in folder: URL, sortByTime: Bool = true) async throws -> [SequenceInfo] {
        let accessed = folder.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                folder.stopAccessingSecurityScopedResource()
            }
        }
        return try await SequenceLister.listSequence(in: folder, sortByTime: sortByTime)
    }

    /// Downscaled preview image (max pixel dimension `maxDimension`) as JPEG data.
    public func preview(of url: URL, maxDimension: Int) async throws -> Data {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }
        return try await PreviewRenderer.renderPreview(of: url, maxDimension: maxDimension)
    }

    /// Detect reference stars in the reference frame (automatic mode helper for the viewfinder).
    public func detectStars(in url: URL, config: JobConfig) async throws -> DetectionResult {
        let accessed = url.startAccessingSecurityScopedResource()
        defer {
            if accessed {
                url.stopAccessingSecurityScopedResource()
            }
        }

        let luma = try ImageDecoder.decodeLuma(
            from: url,
            rawNoiseReduction: config.rawNoiseReduction,
            rawExposureEV: config.rawExposureEV
        )

        let detector = StarDetector()
        let detected = detector.detectStars(
            in: luma,
            maxStars: 100,
            noisyRawRecovery: config.rawNoiseReduction
        )

        let starPoints = detected.map(\.point)
        guard !starPoints.isEmpty else {
            return DetectionResult(
                referenceImage: url,
                referenceStars: [],
                secondStar: nil,
                confidence: 0.0
            )
        }

        let primary = starPoints[0]
        var candidateSecondStar: CGPoint? = nil

        // Find candidate for rotation reference: star with highest separation from primary
        if starPoints.count > 1 {
            var maxDistance: Double = 0.0
            for point in starPoints.dropFirst() {
                let dx = Double(point.x - primary.x)
                let dy = Double(point.y - primary.y)
                let dist = sqrt(dx * dx + dy * dy)
                if dist > maxDistance {
                    maxDistance = dist
                    candidateSecondStar = point
                }
            }
        }

        let avgSNR = detected.reduce(0.0) { $0 + Double($1.snr) } / Double(detected.count)
        let countFactor = min(1.0, Double(detected.count) / 12.0)
        let snrFactor = min(1.0, avgSNR / 5.0)
        let confidence = max(0.1, min(1.0, countFactor * 0.6 + snrFactor * 0.4))

        return DetectionResult(
            referenceImage: url,
            referenceStars: starPoints,
            secondStar: candidateSecondStar,
            confidence: confidence
        )
    }

    /// Hardware description for the Processing hardware UI.
    public func computeInfo() -> String {
        #if canImport(Metal)
        let deviceName = MTLCreateSystemDefaultDevice()?.name ?? "Apple GPU"
        #else
        let deviceName = "Apple GPU"
        #endif
        let gpuName = deviceName.contains("GPU") ? deviceName : "\(deviceName) GPU"
        let cores = ProcessInfo.processInfo.activeProcessorCount
        return "\(gpuName) · \(cores) CPU cores"
    }

    /// Run a full alignment and stacking job.
    ///
    /// Yields live state updates and guarantees termination after a terminal status
    /// (`.completed`, `.cancelled`, or `.failed`).
    public func run(_ config: JobConfig) -> AsyncStream<JobState> {
        AsyncStream { continuation in
            let context = JobExecutionContext(
                config: config,
                computeDescription: self.computeInfo(),
                continuation: continuation
            )

            let runTask = Task {
                // 1. Security-scoped directory access
                let inputAccess = config.inputDirectory.startAccessingSecurityScopedResource()
                let outputAccess = config.outputDirectory.startAccessingSecurityScopedResource()
                var convAccess = false
                if let convDir = config.conversionOutputDirectory {
                    convAccess = convDir.startAccessingSecurityScopedResource()
                }
                defer {
                    if inputAccess { config.inputDirectory.stopAccessingSecurityScopedResource() }
                    if outputAccess { config.outputDirectory.stopAccessingSecurityScopedResource() }
                    if convAccess { config.conversionOutputDirectory?.stopAccessingSecurityScopedResource() }
                }

                // 2. Early validation check
                if let validationError = config.validationError() {
                    context.fail(error: validationError)
                    return
                }

                var createdConversionDirectory: URL? = nil

                func cleanupPartialOutputs() {
                    let ext = config.imageFormat.rawValue
                    let baseName = (config.outputBaseName as NSString).pathExtension.lowercased() == ext.lowercased()
                        ? config.outputBaseName
                        : "\(config.outputBaseName).\(ext)"
                    let finalImageURL = config.outputDirectory.appendingPathComponent(baseName)
                    try? FileManager.default.removeItem(at: finalImageURL)

                    let livePreviewURL = config.outputDirectory.appendingPathComponent("\(config.outputBaseName).live.jpg")
                    try? FileManager.default.removeItem(at: livePreviewURL)

                    let cachesDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
                        ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
                    let cacheLivePreviewURL = cachesDir.appendingPathComponent("\(config.outputBaseName).live.jpg")
                    try? FileManager.default.removeItem(at: cacheLivePreviewURL)

                    let mp4Video = config.outputDirectory.appendingPathComponent("\(config.outputBaseName).mp4")
                    try? FileManager.default.removeItem(at: mp4Video)
                    let movVideo = config.outputDirectory.appendingPathComponent("\(config.outputBaseName).mov")
                    try? FileManager.default.removeItem(at: movVideo)

                    let framesDir = config.outputDirectory.appendingPathComponent("\(config.outputBaseName)_frames")
                    if !config.noStack {
                        try? FileManager.default.removeItem(at: framesDir)
                    }

                    let checkpointDir = config.outputDirectory.appendingPathComponent(".pullstar_checkpoints")
                    if !config.useCheckpoint {
                        try? FileManager.default.removeItem(at: checkpointDir)
                    }

                    if let convDir = createdConversionDirectory {
                        try? FileManager.default.removeItem(at: convDir)
                    }
                }

                do {
                    try Task.checkCancellation()

                    // =========================================================
                    // STAGE 1: PREPARATION
                    // =========================================================
                    context.updateStageProgress(stage: .preparation, stageProgress: 0.0)

                    // Ensure output directory exists
                    try FileManager.default.createDirectory(at: config.outputDirectory, withIntermediateDirectories: true)

                    // List sequence
                    let fullSequence = try await SequenceLister.listSequence(in: config.inputDirectory, sortByTime: config.sortByTime)
                    let sequence = fullSequence.filter { info in
                        let name = info.url.lastPathComponent
                        return !name.hasSuffix(".live.jpg") && !name.hasPrefix(".")
                    }

                    let minRequired = (config.noStack || config.polaris != nil) ? 1 : 3
                    guard sequence.count >= minRequired else {
                        throw IOError.cannotDecodeImage(
                            config.inputDirectory,
                            reason: "Insufficient frames in sequence (found \(sequence.count), required at least \(minRequired))."
                        )
                    }

                    context.setFrameCount(sequence.count)
                    context.updateStageProgress(stage: .preparation, stageProgress: 1.0)

                    // =========================================================
                    // STAGE 2: CONVERSION (if requested)
                    // =========================================================
                    var workingURLs = sequence.map(\.url)

                    if config.conversionFormat != .none {
                        try Task.checkCancellation()
                        context.updateStageProgress(stage: .conversion, stageProgress: 0.0)

                        if config.conversionOutputDirectory == nil {
                            let tempDir = config.inputDirectory.appendingPathComponent(".staraligner-converted-\(UUID().uuidString)")
                            createdConversionDirectory = tempDir
                        }

                        var convConfig = config
                        if let createdConversionDirectory {
                            convConfig.conversionOutputDirectory = createdConversionDirectory
                        }

                        let converted = try ImageWriter.convertInputs(sources: workingURLs, config: convConfig) { progressFrac, cur, tot in
                            context.updateStageProgress(stage: .conversion, stageProgress: progressFrac, current: cur, total: tot)
                        }

                        try Task.checkCancellation()
                        workingURLs = converted
                        context.updateStageProgress(stage: .conversion, stageProgress: 1.0)
                    }

                    let finalWorkingURLs = workingURLs

                    // =========================================================
                    // STAGE 3: PASS 1 (Alignment analysis)
                    // =========================================================
                    try Task.checkCancellation()
                    context.updateStageProgress(stage: .pass1, stageProgress: 0.0, current: 0)

                    let pass1StartTime = ProcessInfo.processInfo.systemUptime
                    let lastFPSTime = LockProtected(pass1StartTime)
                    let fpsSmoothed = LockProtected(0.0)

                    let baseDate = sequence.first?.captureDate
                    let times: [Double] = sequence.map { info in
                        if let d = info.captureDate, let b = baseDate {
                            return d.timeIntervalSince(b)
                        }
                        return -1.0
                    }

                    // Bounded memory: load luma on demand per frame
                    let loadLuma: @Sendable (Int) async throws -> PixelImage = { index in
                        try Task.checkCancellation()
                        let url = finalWorkingURLs[index]
                        return try ImageDecoder.decodeLuma(
                            from: url,
                            rawNoiseReduction: config.rawNoiseReduction,
                            rawExposureEV: config.rawExposureEV
                        )
                    }

                    let analyzer = AlignmentAnalyzer()
                    let analysisResult = try await analyzer.analyze(
                        frameCount: finalWorkingURLs.count,
                        loadLuma: loadLuma,
                        times: times,
                        config: config,
                        progress: { current, total, driftX, driftY in
                            let now = ProcessInfo.processInfo.systemUptime
                            lastFPSTime.withLock { lastTime in
                                if now - lastTime > 0.1 {
                                    let instantFps = Double(current) / max(0.001, now - pass1StartTime)
                                    fpsSmoothed.withLock { fps in
                                        fps = fps > 0 ? (0.7 * fps + 0.3 * instantFps) : instantFps
                                    }
                                    lastTime = now
                                }
                            }
                            let currentFPS = fpsSmoothed.withLock { $0 }
                            context.updatePass1(
                                current: current,
                                total: total,
                                driftX: driftX,
                                driftY: driftY,
                                fps: currentFPS
                            )
                        }
                    )

                    context.setDetection(DetectionResult(
                        referenceImage: finalWorkingURLs.first ?? config.inputDirectory,
                        referenceStars: analysisResult.referenceStars,
                        secondStar: config.secondStar,
                        confidence: analysisResult.confidence
                    ))

                    context.updateStageProgress(stage: .pass1, stageProgress: 1.0)

                    // =========================================================
                    // STAGE 4: CROP CALCULATION
                    // =========================================================
                    try Task.checkCancellation()
                    context.updateStageProgress(stage: .cropCalc, stageProgress: 0.0)

                    let crop = analysisResult.crop
                    guard crop.width > 0 && crop.height > 0 else {
                        throw NSError(
                            domain: "PullStarEngine",
                            code: 2,
                            userInfo: [NSLocalizedDescriptionKey: "Calculated crop region is empty or invalid."]
                        )
                    }
                    context.updateStageProgress(stage: .cropCalc, stageProgress: 1.0)

                    // =========================================================
                    // STAGE 5: PASS 2 (Stacking & Warping)
                    // =========================================================
                    try Task.checkCancellation()
                    context.updateStageProgress(stage: .pass2, stageProgress: 0.0, current: 0)

                    // Forward frame loader on demand
                    let loadFrame: @Sendable (Int) async throws -> PixelImage = { index in
                        try Task.checkCancellation()
                        let url = finalWorkingURLs[index]
                        return try ImageDecoder.shared.decode(
                            from: url,
                            rawNoiseReduction: config.rawNoiseReduction,
                            rawExposureEV: config.rawExposureEV
                        )
                    }

                    let cachesDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
                        ?? URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
                    let cacheLivePreviewURL = cachesDir.appendingPathComponent("\(config.outputBaseName).live.jpg")

                    let pipelineResult = try await StackPipeline.run(
                        frameCount: finalWorkingURLs.count,
                        transforms: analysisResult.transforms,
                        crop: crop,
                        config: config,
                        loadFrame: loadFrame,
                        progress: { pipelineState in
                            // Atomically write live preview JPEG to caches directory with revision
                            if let liveURL = pipelineState.livePreviewURL,
                               let data = try? Data(contentsOf: liveURL) {
                                try? data.write(to: cacheLivePreviewURL, options: .atomic)
                                context.updateLivePreview(url: cacheLivePreviewURL, revision: pipelineState.livePreviewRevision)
                            }

                            if pipelineState.stage == .videoRender {
                                context.updateStageProgress(
                                    stage: .videoRender,
                                    stageProgress: pipelineState.progress,
                                    current: pipelineState.current,
                                    total: pipelineState.total
                                )
                            } else if pipelineState.stage == .pass2 {
                                context.updateStageProgress(
                                    stage: .pass2,
                                    stageProgress: pipelineState.progress,
                                    current: pipelineState.current,
                                    total: pipelineState.total
                                )
                            }
                        }
                    )

                    // =========================================================
                    // STAGE 6: OUTPUTS & FINALIZATION
                    // =========================================================
                    try Task.checkCancellation()

                    let ext = config.imageFormat.rawValue
                    let baseName = (config.outputBaseName as NSString).pathExtension.lowercased() == ext.lowercased()
                        ? config.outputBaseName
                        : "\(config.outputBaseName).\(ext)"
                    let finalImageURL = config.outputDirectory.appendingPathComponent(baseName)

                    let framesDir: URL? = config.saveFrames
                        ? (config.noStack ? config.outputDirectory : config.outputDirectory.appendingPathComponent("\(config.outputBaseName)_frames"))
                        : nil

                    let resultURL: URL
                    if !config.noStack {
                        if let finalImage = pipelineResult.finalImage {
                            try ImageWriter.write(finalImage, to: finalImageURL, format: config.imageFormat)
                        }
                        resultURL = finalImageURL
                    } else {
                        // Images-only mode: result is the frames directory (or outputDirectory in noStack mode)
                        resultURL = framesDir ?? config.outputDirectory
                    }

                    // Clean temporary live preview in output folder
                    let liveInOutputDir = config.outputDirectory.appendingPathComponent("\(config.outputBaseName).live.jpg")
                    try? FileManager.default.removeItem(at: liveInOutputDir)

                    // Clean temporary conversion directory if one was created
                    if let convDir = createdConversionDirectory {
                        try? FileManager.default.removeItem(at: convDir)
                    }

                    context.complete(
                        resultURL: resultURL,
                        videoURL: pipelineResult.videoURL,
                        framesDir: framesDir,
                        frameCount: (config.saveFrames || config.noStack) ? pipelineResult.exportedFrameURLs.count : nil
                    )

                } catch is CancellationError {
                    context.cancelling()
                    cleanupPartialOutputs()
                    context.cancel()
                } catch {
                    if Task.isCancelled {
                        context.cancelling()
                        cleanupPartialOutputs()
                        context.cancel()
                    } else {
                        cleanupPartialOutputs()
                        context.fail(error: error.localizedDescription)
                    }
                }
            }

            continuation.onTermination = { @Sendable _ in
                runTask.cancel()
            }
        }
    }
}

// MARK: - Internal Concurrency & State Management

private final class JobExecutionContext: @unchecked Sendable {
    private let lock = NSLock()
    private var state: JobState
    private var maxOverallProgress = 0.0
    private let config: JobConfig
    private let continuation: AsyncStream<JobState>.Continuation

    init(config: JobConfig, computeDescription: String, continuation: AsyncStream<JobState>.Continuation) {
        self.config = config
        self.continuation = continuation
        var initial = JobState()
        initial.status = .running
        initial.computeDescription = computeDescription
        self.state = initial
    }

    func setFrameCount(_ count: Int) {
        lock.lock()
        state.total = count
        state.frameCount = count
        let snapshot = state
        lock.unlock()
        continuation.yield(snapshot)
    }

    func updateStageProgress(
        stage: JobStage,
        stageProgress: Double,
        current: Int? = nil,
        total: Int? = nil
    ) {
        lock.lock()
        // Stages only move forward (preparation → conversion → pass1 → crop_calc → pass2 →
        // video_render → done); a late progress callback must not report an earlier stage.
        let order: [JobStage] = [.preparation, .conversion, .pass1, .cropCalc, .pass2, .videoRender, .done]
        if let current = state.stage, let ci = order.firstIndex(of: current),
           let ni = order.firstIndex(of: stage), ni < ci {
            lock.unlock()
            return
        }
        state.stage = stage
        state.progress = max(0.0, min(1.0, stageProgress))
        if let current { state.current = current }
        if let total { state.total = total }

        let stackingEnd = (config.videoEnabled && !config.noStack) ? 0.95 : 0.99
        let (stageStart, stageEnd): (Double, Double) = {
            if config.conversionFormat != .none {
                switch stage {
                case .preparation: return (0.00, 0.05)
                case .conversion:  return (0.05, 0.20)
                case .pass1:       return (0.20, 0.35)
                case .cropCalc:    return (0.35, 0.40)
                case .pass2:       return (0.40, stackingEnd)
                case .videoRender: return (0.95, 0.99)
                case .done:        return (1.00, 1.00)
                }
            } else {
                switch stage {
                case .preparation: return (0.00, 0.05)
                case .conversion:  return (0.05, 0.05)
                case .pass1:       return (0.05, 0.35)
                case .cropCalc:    return (0.35, 0.40)
                case .pass2:       return (0.40, stackingEnd)
                case .videoRender: return (0.95, 0.99)
                case .done:        return (1.00, 1.00)
                }
            }
        }()

        let currentStageSpan = stageEnd - stageStart
        let computedOverall = stageStart + (currentStageSpan * state.progress)
        maxOverallProgress = max(maxOverallProgress, computedOverall)
        state.overallProgress = min(1.0, maxOverallProgress)
        let snapshot = state
        lock.unlock()

        continuation.yield(snapshot)
    }

    func updatePass1(current: Int, total: Int, driftX: Double, driftY: Double, fps: Double) {
        lock.lock()
        state.current = current
        state.total = total
        if current == total || (driftX != 0 || driftY != 0) {
            state.driftX = driftX
            state.driftY = driftY
        }
        state.framesPerSecond = fps
        let prog = total > 0 ? Double(current) / Double(total) : 0.0
        lock.unlock()
        updateStageProgress(stage: .pass1, stageProgress: prog)
    }

    func updateLivePreview(url: URL, revision: Int) {
        lock.lock()
        state.livePreviewURL = url
        state.livePreviewRevision = revision
        let snapshot = state
        lock.unlock()
        continuation.yield(snapshot)
    }

    func setDetection(_ detection: DetectionResult) {
        lock.lock()
        state.detection = detection
        let snapshot = state
        lock.unlock()
        continuation.yield(snapshot)
    }

    func complete(resultURL: URL?, videoURL: URL?, framesDir: URL?, frameCount: Int?) {
        lock.lock()
        state.status = .completed
        state.stage = .done
        state.progress = 1.0
        state.overallProgress = 1.0
        if let resultURL { state.resultURL = resultURL }
        if let videoURL { state.videoURL = videoURL }
        if let framesDir { state.framesDirectory = framesDir }
        if let frameCount { state.frameCount = frameCount }
        let snapshot = state
        lock.unlock()

        continuation.yield(snapshot)
        continuation.finish()
    }

    func fail(error: String) {
        lock.lock()
        state.status = .failed
        state.error = error
        let snapshot = state
        lock.unlock()

        continuation.yield(snapshot)
        continuation.finish()
    }

    func cancelling() {
        lock.lock()
        state.status = .cancelling
        let snapshot = state
        lock.unlock()
        continuation.yield(snapshot)
    }

    func cancel() {
        lock.lock()
        state.status = .cancelled
        let snapshot = state
        lock.unlock()

        continuation.yield(snapshot)
        continuation.finish()
    }
}

private final class LockProtected<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T

    init(_ value: T) {
        self.value = value
    }

    func withLock<R>(_ body: (inout T) throws -> R) rethrows -> R {
        lock.lock()
        defer { lock.unlock() }
        return try body(&value)
    }
}
