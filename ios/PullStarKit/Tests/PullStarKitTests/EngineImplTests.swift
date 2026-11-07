import Testing
import Foundation
import CoreGraphics
import AVFoundation
@testable import PullStarKit

// MARK: - Synthetic Sky Sequence Helpers

private func generateCatalog(count: Int = 35, width: Int = 420, height: Int = 320, seed: UInt64 = 202) -> [(x: Double, y: Double, peak: Float, sigma: Double)] {
    var stars: [(x: Double, y: Double, peak: Float, sigma: Double)] = []
    var state = seed
    let margin = 45.0
    for _ in 0..<count {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let rx = Double(state >> 32) / Double(UInt32.max)
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let ry = Double(state >> 32) / Double(UInt32.max)
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let rp = Float(state >> 32) / Float(UInt32.max)

        let x = margin + rx * (Double(width) - 2 * margin)
        let y = margin + ry * (Double(height) - 2 * margin)
        let peak = 0.5 + rp * 0.5
        stars.append((x: x, y: y, peak: peak, sigma: 1.4))
    }
    return stars
}

private func renderSkyFrame(
    width: Int = 420,
    height: Int = 320,
    stars: [(x: Double, y: Double, peak: Float, sigma: Double)]
) -> PixelImage {
    var luma = [Float](repeating: 0.03, count: width * height)

    for star in stars {
        let radius = Int(ceil(star.sigma * 4.0))
        let minX = max(0, Int(star.x) - radius)
        let maxX = min(width - 1, Int(star.x) + radius)
        let minY = max(0, Int(star.y) - radius)
        let maxY = min(height - 1, Int(star.y) + radius)
        let twoSigma2 = 2.0 * star.sigma * star.sigma

        for y in minY...maxY {
            let dy = Double(y) - star.y
            let row = y * width
            for x in minX...maxX {
                let dx = Double(x) - star.x
                let dist2 = dx * dx + dy * dy
                let val = star.peak * Float(exp(-dist2 / twoSigma2))
                luma[row + x] += val
            }
        }
    }

    var rgb = [Float](repeating: 0, count: width * height * 3)
    for i in 0..<(width * height) {
        let v = min(1.0, luma[i])
        rgb[i * 3 + 0] = v
        rgb[i * 3 + 1] = v
        rgb[i * 3 + 2] = v
    }
    return PixelImage(width: width, height: height, channels: 3, data: rgb)
}

private func createSyntheticSequence(
    in directory: URL,
    frameCount: Int = 12,
    width: Int = 420,
    height: Int = 320
) throws -> [URL] {
    let catalog = generateCatalog(count: 35, width: width, height: height)
    let poleX = -280.0
    let poleY = -150.0
    let dTheta = 0.3 * Double.pi / 180.0
    let baseDate = Date().addingTimeInterval(-3600)

    var urls: [URL] = []
    let fm = FileManager.default

    for i in 0..<frameCount {
        let theta = Double(i) * dTheta
        let sign = (i % 2 == 0) ? 1.0 : -1.0
        let wobbleX = sign * 2.5
        let wobbleY = -sign * 1.5

        let cosT = cos(theta)
        let sinT = sin(theta)

        var frameStars: [(x: Double, y: Double, peak: Float, sigma: Double)] = []
        for s in catalog {
            let dx = s.x - poleX
            let dy = s.y - poleY
            let rotX = poleX + (cosT * dx - sinT * dy) + wobbleX
            let rotY = poleY + (sinT * dx + cosT * dy) + wobbleY
            frameStars.append((x: rotX, y: rotY, peak: s.peak, sigma: s.sigma))
        }

        let pixelImage = renderSkyFrame(width: width, height: height, stars: frameStars)
        let filename = String(format: "frame_%04d.png", i)
        let fileURL = directory.appendingPathComponent(filename)

        try ImageWriter.writePNG(pixelImage, to: fileURL)

        // Set modification time for sortByTime sorting
        let modDate = baseDate.addingTimeInterval(Double(i) * 20.0)
        try? fm.setAttributes([.modificationDate: modDate], ofItemAtPath: fileURL.path)

        urls.append(fileURL)
    }

    return urls
}

// MARK: - PullStarEngineImpl Tests

@Suite("Engine Implementation End-to-End Tests")
struct EngineImplTests {

    @Test("PullStarEngineImpl lists sequence, renders preview, detects stars, and reports compute info")
    func testEngineProtocolMethods() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let frameURLs = try createSyntheticSequence(in: tempDir, frameCount: 12)
        #expect(frameURLs.count == 12)

        let engine = PullStarEngineImpl()

        // 1. computeInfo
        let compute = engine.computeInfo()
        #expect(!compute.isEmpty)
        #expect(compute.contains("cores"))

        // 2. listSequence
        let sequence = try await engine.listSequence(in: tempDir, sortByTime: true)
        #expect(sequence.count == 12)
        #expect(sequence.first?.name == "frame_0000.png")

        // 3. preview
        let previewData = try await engine.preview(of: frameURLs[0], maxDimension: 256)
        #expect(!previewData.isEmpty)
        #expect(previewData.count > 4)
        #expect(previewData[0] == 0xFF && previewData[1] == 0xD8)

        // 4. detectStars
        let config = JobConfig(inputDirectory: tempDir, outputDirectory: tempDir)
        let detection = try await engine.detectStars(in: frameURLs[0], config: config)
        #expect(detection.referenceStars.count >= 6)
        #expect(detection.secondStar != nil)
        #expect(detection.confidence > 0.0)
    }

    @Test("PullStarEngineImpl runs end-to-end alignment and stacking with video export")
    func testEndToEndRun() async throws {
        let inputDir = FileManager.default.temporaryDirectory.appendingPathComponent("input_\(UUID().uuidString)")
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent("output_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: inputDir)
            try? FileManager.default.removeItem(at: outputDir)
        }

        _ = try createSyntheticSequence(in: inputDir, frameCount: 12)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: outputDir)
        config.outputBaseName = "e2e_result"
        config.imageFormat = .tiff
        config.videoEnabled = true
        config.videoFPS = 24
        config.saveFrames = true
        config.extensionFactor = 1.0

        let engine = PullStarEngineImpl()
        var states: [JobState] = []
        var maxDrift = 0.0

        for await state in engine.run(config) {
            states.append(state)
            if abs(state.driftX) > maxDrift { maxDrift = abs(state.driftX) }
            if abs(state.driftY) > maxDrift { maxDrift = abs(state.driftY) }
        }

        #expect(!states.isEmpty)

        guard let finalState = states.last else {
            Issue.record("No final state produced")
            return
        }

        #expect(finalState.status == JobStatus.completed)
        #expect(finalState.stage == JobStage.done)
        #expect(finalState.overallProgress == 1.0)
        #expect(finalState.error == nil)
        #expect(!finalState.computeDescription.isEmpty)

        // Verify result image exists
        guard let resultURL = finalState.resultURL else {
            Issue.record("finalState.resultURL is nil")
            return
        }
        #expect(FileManager.default.fileExists(atPath: resultURL.path))
        let imageAttrs = try FileManager.default.attributesOfItem(atPath: resultURL.path)
        let imageSize = imageAttrs[.size] as? Int64 ?? 0
        #expect(imageSize > 0)
        #expect(resultURL.lastPathComponent == "e2e_result.tiff")

        // Verify trail video was created and exists
        guard let videoURL = finalState.videoURL else {
            Issue.record("finalState.videoURL is nil")
            return
        }
        #expect(FileManager.default.fileExists(atPath: videoURL.path))
        let videoAttrs = try FileManager.default.attributesOfItem(atPath: videoURL.path)
        let videoSize = videoAttrs[.size] as? Int64 ?? 0
        #expect(videoSize > 0)

        // Verify drift was reported during tracking
        #expect(maxDrift > 0.0, "Drift was not reported")

        // Verify live preview was published
        let hadLivePreview = states.contains { $0.livePreviewURL != nil && $0.livePreviewRevision > 0 }
        #expect(hadLivePreview, "Live preview was not published")

        // Verify frames directory exists when saveFrames is true
        guard let framesDir = finalState.framesDirectory else {
            Issue.record("finalState.framesDirectory is nil")
            return
        }
        #expect(FileManager.default.fileExists(atPath: framesDir.path))
        let exportedFiles = try FileManager.default.contentsOfDirectory(atPath: framesDir.path)
        #expect(exportedFiles.contains("sequence.json"))
        #expect(exportedFiles.count >= 10)
    }

    @Test("PullStarEngineImpl appends extension only when missing")
    func testOutputBaseNameExtensionHandling() async throws {
        let inputDir = FileManager.default.temporaryDirectory.appendingPathComponent("input_\(UUID().uuidString)")
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent("output_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: inputDir)
            try? FileManager.default.removeItem(at: outputDir)
        }

        _ = try createSyntheticSequence(in: inputDir, frameCount: 4)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: outputDir)
        // Already includes .tiff
        config.outputBaseName = "already_has_ext.tiff"
        config.imageFormat = .tiff
        config.saveFrames = false
        config.videoEnabled = false

        let engine = PullStarEngineImpl()
        var states: [JobState] = []
        for await state in engine.run(config) {
            states.append(state)
        }

        guard let finalState = states.last else {
            Issue.record("No final state produced")
            return
        }

        #expect(finalState.status == JobStatus.completed)
        guard let resultURL = finalState.resultURL else {
            Issue.record("resultURL is nil")
            return
        }
        // Should NOT be "already_has_ext.tiff.tiff"
        #expect(resultURL.lastPathComponent == "already_has_ext.tiff")
        #expect(FileManager.default.fileExists(atPath: resultURL.path))
    }

    @Test("PullStarEngineImpl handles images-only noStack mode")
    func testNoStackMode() async throws {
        let inputDir = FileManager.default.temporaryDirectory.appendingPathComponent("input_\(UUID().uuidString)")
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent("output_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: inputDir)
            try? FileManager.default.removeItem(at: outputDir)
        }

        _ = try createSyntheticSequence(in: inputDir, frameCount: 12)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: outputDir)
        config.outputBaseName = "nostack_test"
        config.noStack = true
        config.saveFrames = true
        config.imageFormat = .png

        let engine = PullStarEngineImpl()
        var states: [JobState] = []

        for await state in engine.run(config) {
            states.append(state)
        }

        guard let finalState = states.last else {
            Issue.record("No final state produced")
            return
        }

        #expect(finalState.status == JobStatus.completed)
        #expect(finalState.stage == JobStage.done)

        // In noStack mode, output directory contains the warped frames and sequence.json
        guard let resultURL = finalState.resultURL else {
            Issue.record("finalState.resultURL is nil")
            return
        }
        #expect(FileManager.default.fileExists(atPath: resultURL.path))
        let exportedFiles = try FileManager.default.contentsOfDirectory(atPath: resultURL.path)
        #expect(exportedFiles.contains("sequence.json"))
        #expect(exportedFiles.contains(where: { $0.hasSuffix(".png") }))

        // No stacked result image should be written
        let stackedFile = outputDir.appendingPathComponent("nostack_test.png")
        #expect(!FileManager.default.fileExists(atPath: stackedFile.path))
    }

    @Test("PullStarEngineImpl runs conversion stage when conversionFormat != none")
    func testConversionStage() async throws {
        let inputDir = FileManager.default.temporaryDirectory.appendingPathComponent("input_\(UUID().uuidString)")
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent("output_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: inputDir)
            try? FileManager.default.removeItem(at: outputDir)
        }

        _ = try createSyntheticSequence(in: inputDir, frameCount: 4)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: outputDir)
        config.outputBaseName = "conversion_test"
        config.conversionFormat = .jpg
        config.imageFormat = .tiff
        config.saveFrames = false

        let engine = PullStarEngineImpl()
        var states: [JobState] = []
        for await state in engine.run(config) {
            states.append(state)
        }

        let sawConversion = states.contains { $0.stage == .conversion }
        #expect(sawConversion, "Conversion stage was not run")

        let finalState = states.last
        #expect(finalState?.status == .completed)
    }

    @Test("PullStarEngineImpl respects cancellation and cleans up partial output")
    func testCancellation() async throws {
        let inputDir = FileManager.default.temporaryDirectory.appendingPathComponent("input_\(UUID().uuidString)")
        let outputDir = FileManager.default.temporaryDirectory.appendingPathComponent("output_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
        defer {
            try? FileManager.default.removeItem(at: inputDir)
            try? FileManager.default.removeItem(at: outputDir)
        }

        _ = try createSyntheticSequence(in: inputDir, frameCount: 12)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: outputDir)
        config.outputBaseName = "cancel_test"
        config.extensionFactor = 1.0

        let engine = PullStarEngineImpl()

        let runTask = Task { () -> [JobState] in
            var collected: [JobState] = []
            for await state in engine.run(config) {
                collected.append(state)
            }
            return collected
        }

        // Allow engine to start running
        try await Task.sleep(nanoseconds: 50_000_000)
        runTask.cancel()

        let states = await runTask.value
        #expect(!states.isEmpty)

        // Wait briefly for engine catch block and background cleanup to finish
        try await Task.sleep(nanoseconds: 100_000_000)

        // Verify cancel stopped execution before final image was generated
        let finalImage = outputDir.appendingPathComponent("cancel_test.tiff")
        #expect(!FileManager.default.fileExists(atPath: finalImage.path))

        // Live preview file in output directory should be cleaned up
        let liveFile = outputDir.appendingPathComponent("cancel_test.live.jpg")
        #expect(!FileManager.default.fileExists(atPath: liveFile.path))
    }

    @Test("PullStarEngineImpl handles invalid config and missing directory gracefully")
    func testInvalidConfigAndMissingDirectory() async throws {
        let dummyURL = FileManager.default.temporaryDirectory.appendingPathComponent("nonexistent_\(UUID().uuidString)")

        let engine = PullStarEngineImpl()

        // 1. Validation error: noStack without saveFrames
        var invalidConfig = JobConfig(inputDirectory: dummyURL, outputDirectory: dummyURL)
        invalidConfig.noStack = true
        invalidConfig.saveFrames = false

        var states1: [JobState] = []
        for await state in engine.run(invalidConfig) {
            states1.append(state)
        }

        #expect(states1.count == 1)
        #expect(states1.first?.status == JobStatus.failed)
        #expect(states1.first?.error != nil)

        // 2. Missing input directory
        var missingDirConfig = JobConfig(inputDirectory: dummyURL, outputDirectory: dummyURL)
        missingDirConfig.saveFrames = false
        missingDirConfig.noStack = false

        var states2: [JobState] = []
        for await state in engine.run(missingDirConfig) {
            states2.append(state)
        }

        #expect(!states2.isEmpty)
        let lastState = states2.last!
        #expect(lastState.status == JobStatus.failed)
        #expect(lastState.error != nil)
    }
}
