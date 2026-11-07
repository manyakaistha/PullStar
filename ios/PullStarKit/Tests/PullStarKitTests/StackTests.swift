import Testing
import Foundation
import CoreGraphics
import AVFoundation
import CoreMedia
@testable import PullStarKit

struct StackTests {

    // MARK: - Helpers

    /// Creates a synthetic PixelImage with a single star (Gaussian-like dot) at (starX, starY).
    private static func createSyntheticFrame(
        width: Int = 100,
        height: Int = 100,
        starX: Int,
        starY: Int,
        starRadius: Int = 2,
        brightness: Float = 1.0,
        background: Float = 0.0
    ) -> PixelImage {
        var image = PixelImage(width: width, height: height, channels: 3)
        let ch = 3
        for y in 0..<height {
            for x in 0..<width {
                let idx = (y * width + x) * ch
                let dx = x - starX
                let dy = y - starY
                let distSq = dx * dx + dy * dy
                let val: Float
                if distSq <= starRadius * starRadius {
                    val = brightness * (1.0 - Float(distSq) / Float(starRadius * starRadius + 1))
                } else {
                    val = background
                }
                image.data[idx] = val
                image.data[idx + 1] = val
                image.data[idx + 2] = val
            }
        }
        return image
    }

    // MARK: - FrameWarper Tests

    @Test func frameWarperIntegerTranslation() throws {
        let warper = FrameWarper()
        let src = Self.createSyntheticFrame(width: 80, height: 80, starX: 40, starY: 40, starRadius: 1)

        // Translation by tx = 5, ty = 3
        var transform = FrameTransform()
        transform.tx = 5.0
        transform.ty = 3.0

        let crop = CropRegion(x: 10, y: 10, width: 60, height: 60)
        let warped = try warper.warp(image: src, transform: transform, crop: crop, backend: .cpu)

        #expect(warped.width == 60)
        #expect(warped.height == 60)

        // Expected coordinate in crop:
        // dest_x = src_x + tx => in crop: (40 + 5) - crop.x = 45 - 10 = 35
        // dest_y = src_y + ty => in crop: (40 + 3) - crop.y = 43 - 10 = 33
        let expectedX = 35
        let expectedY = 33
        let starIdx = (expectedY * 60 + expectedX) * 3
        #expect(warped.data[starIdx] > 0.8)

        // Verify outside star is black
        let originIdx = (0 * 60 + 0) * 3
        #expect(warped.data[originIdx] == 0.0)
    }

    @Test func frameWarperSubpixelLanczos4() throws {
        let warper = FrameWarper()
        let src = Self.createSyntheticFrame(width: 60, height: 60, starX: 30, starY: 30, starRadius: 2)

        var transform = FrameTransform()
        transform.tx = 2.5
        transform.ty = 1.25

        let crop = CropRegion(x: 5, y: 5, width: 50, height: 50)
        let warped = try warper.warp(image: src, transform: transform, crop: crop, backend: .cpu)

        #expect(warped.width == 50)
        #expect(warped.height == 50)

        // Target center around x = 30 + 2.5 - 5 = 27.5, y = 30 + 1.25 - 5 = 26.25
        let idx1 = (26 * 50 + 27) * 3
        let idx2 = (26 * 50 + 28) * 3
        #expect(warped.data[idx1] > 0.3)
        #expect(warped.data[idx2] > 0.3)
    }

    @Test func frameWarperGPUAndCPUEquivalence() throws {
        let warper = FrameWarper()
        guard warper.device != nil else {
            // Headless / Metal unavailable
            return
        }

        let src = Self.createSyntheticFrame(width: 64, height: 64, starX: 32, starY: 32, starRadius: 3)
        var transform = FrameTransform()
        transform.tx = 3.25
        transform.ty = 2.75

        let crop = CropRegion(x: 4, y: 4, width: 56, height: 56)
        let cpuWarped = try warper.warp(image: src, transform: transform, crop: crop, backend: .cpu)
        let gpuWarped = try warper.warp(image: src, transform: transform, crop: crop, backend: .gpu)

        #expect(cpuWarped.width == gpuWarped.width)
        #expect(cpuWarped.height == gpuWarped.height)

        var maxDiff: Float = 0
        for i in 0..<cpuWarped.data.count {
            let diff = abs(cpuWarped.data[i] - gpuWarped.data[i])
            if diff > maxDiff { maxDiff = diff }
        }
        #expect(maxDiff < 0.05)
    }

    // MARK: - TrailStacker Tests

    @Test func trailStackerLightenBlend() {
        let stacker = TrailStacker(width: 50, height: 50, channels: 3, blendMode: .lighten)

        let f1 = Self.createSyntheticFrame(width: 50, height: 50, starX: 10, starY: 25, starRadius: 1)
        let f2 = Self.createSyntheticFrame(width: 50, height: 50, starX: 20, starY: 25, starRadius: 1)
        let f3 = Self.createSyntheticFrame(width: 50, height: 50, starX: 30, starY: 25, starRadius: 1)

        stacker.blend(frame: f1)
        stacker.blend(frame: f2)
        stacker.blend(frame: f3)

        let snapshot = stacker.currentSnapshot()

        // All three star points should be bright in the accumulator
        let star1Idx = (25 * 50 + 10) * 3
        let star2Idx = (25 * 50 + 20) * 3
        let star3Idx = (25 * 50 + 30) * 3

        #expect(snapshot.data[star1Idx] > 0.8)
        #expect(snapshot.data[star2Idx] > 0.8)
        #expect(snapshot.data[star3Idx] > 0.8)

        // Empty space should remain black
        let emptyIdx = (25 * 50 + 45) * 3
        #expect(snapshot.data[emptyIdx] == 0.0)
    }

    @Test func trailStackerAddBlend() {
        let stacker = TrailStacker(width: 20, height: 20, channels: 3, blendMode: .add)

        var frame = PixelImage(width: 20, height: 20, channels: 3)
        for i in 0..<frame.data.count { frame.data[i] = 0.25 }

        stacker.blend(frame: frame)
        stacker.blend(frame: frame)
        stacker.blend(frame: frame)

        let snapshot = stacker.currentSnapshot()
        #expect(abs(snapshot.data[0] - 0.75) < 1e-4)
    }

    @Test func trailEffectsTailOpacityAndSchedule() throws {
        let (taper, threshold) = try TrailEffects.validateTailSettings(taperStrength: 0.5, angleThreshold: 45.0)
        #expect(taper == 0.5)
        #expect(threshold == 45.0)

        #expect(TrailEffects.withinTailAngle(angleDegrees: 30.0, thresholdDegrees: 45.0))
        #expect(!TrailEffects.withinTailAngle(angleDegrees: 50.0, thresholdDegrees: 45.0))

        let opStart = TrailEffects.tailOpacity(angleDegrees: 0.0, spanDegrees: 45.0, taperStrength: 0.5)
        #expect(opStart == 1.0)

        let opEnd = TrailEffects.tailOpacity(angleDegrees: 45.0, spanDegrees: 45.0, taperStrength: 0.5)
        #expect(abs(opEnd - 0.5) < 1e-5)

        let items = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        let sampled = TrailEffects.evenlySpaced(items, count: 4)
        #expect(sampled.count == 4)
        #expect(sampled.first == 0)
        #expect(sampled.last == 9)
    }

    @Test func trailStackerCheckpointSaveAndResume() throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let stacker1 = TrailStacker(width: 30, height: 30, channels: 3, blendMode: .lighten)
        let frame = Self.createSyntheticFrame(width: 30, height: 30, starX: 15, starY: 15, starRadius: 1)
        stacker1.blend(frame: frame)

        var config = JobConfig(inputDirectory: tempDir, outputDirectory: tempDir)
        config.tailTaperStrength = 0.3
        config.tailAngleThreshold = 60.0

        try stacker1.saveCheckpoint(to: tempDir, frameIndex: 4, config: config)

        let stacker2 = TrailStacker(width: 30, height: 30, channels: 3, blendMode: .lighten)
        let resumedIndex = stacker2.resumeCheckpoint(from: tempDir, config: config)

        #expect(resumedIndex == 4)
        let resumedSnap = stacker2.currentSnapshot()
        let starIdx = (15 * 30 + 15) * 3
        #expect(resumedSnap.data[starIdx] > 0.8)
    }

    // MARK: - LivePreviewPublisher Tests

    @Test func livePreviewPublisherGeneratesJPEG() {
        let publisher = LivePreviewPublisher(minimumInterval: 0.0)
        let img = Self.createSyntheticFrame(width: 80, height: 80, starX: 40, starY: 40, starRadius: 2)

        let result = publisher.publish(accumulator: img, force: true)
        #expect(result != nil)
        guard let (data, rev) = result else { return }

        #expect(rev == 1)
        #expect(data.count > 100)
        // Check JPEG SOI magic number: 0xFF, 0xD8
        #expect(data[0] == 0xFF && data[1] == 0xD8)
    }

    // MARK: - TrailVideoWriter Tests

    @Test func trailVideoWriterProducesValidAsset() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let videoOut = tempDir.appendingPathComponent("test_trail.mp4")

        let writer = try TrailVideoWriter(
            destinationURL: videoOut,
            sourceWidth: 64,
            sourceHeight: 64,
            fps: 30,
            quality: .high,
            format: .mp4,
            resolution: .source
        )

        #expect(writer.targetWidth % 2 == 0)
        #expect(writer.targetHeight % 2 == 0)

        // Write 10 frames of a moving star
        for i in 0..<10 {
            let frame = Self.createSyntheticFrame(
                width: 64,
                height: 64,
                starX: 10 + i * 4,
                starY: 32,
                starRadius: 2
            )
            try writer.writeSnapshot(image: frame, repeats: 1)
        }

        let finalURL = try await writer.finish()
        #expect(FileManager.default.fileExists(atPath: finalURL.path))

        // Read video with AVAsset to verify structure
        let asset = AVURLAsset(url: finalURL)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        #expect(tracks.count == 1)

        let track = tracks[0]
        let naturalSize = try await track.load(.naturalSize)
        #expect(Int(naturalSize.width) % 2 == 0)
        #expect(Int(naturalSize.height) % 2 == 0)

        let duration = try await asset.load(.duration)
        let seconds = CMTimeGetSeconds(duration)
        #expect(seconds > 0.0)
    }

    @Test func trailVideoWriterProResMOV() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let videoOut = tempDir.appendingPathComponent("test_prores.mov")

        let writer = try TrailVideoWriter(
            destinationURL: videoOut,
            sourceWidth: 60,
            sourceHeight: 60,
            fps: 24,
            quality: .prores,
            format: .mov,
            resolution: .source
        )

        #expect(writer.fileType == .mov)
        #expect(writer.outputURL.pathExtension == "mov")

        for i in 0..<6 {
            let frame = Self.createSyntheticFrame(width: 60, height: 60, starX: 15 + i * 4, starY: 30)
            try writer.writeSnapshot(image: frame, repeats: 1)
        }

        let finalURL = try await writer.finish()
        #expect(FileManager.default.fileExists(atPath: finalURL.path))

        let asset = AVURLAsset(url: finalURL)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        #expect(tracks.count == 1)
    }

    @Test func trailVideoWriterHEVC() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let videoOut = tempDir.appendingPathComponent("test_hevc.mp4")

        let writer = try TrailVideoWriter(
            destinationURL: videoOut,
            sourceWidth: 64,
            sourceHeight: 64,
            fps: 30,
            quality: .hevc,
            format: .mp4,
            resolution: .source
        )

        #expect(writer.outputURL.pathExtension == "mp4")

        for i in 0..<8 {
            let frame = Self.createSyntheticFrame(width: 64, height: 64, starX: 10 + i * 4, starY: 32)
            try writer.writeSnapshot(image: frame, repeats: 1)
        }

        let finalURL = try await writer.finish()
        #expect(FileManager.default.fileExists(atPath: finalURL.path))

        let asset = AVURLAsset(url: finalURL)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        #expect(tracks.count == 1)
        let duration = try await asset.load(.duration)
        #expect(CMTimeGetSeconds(duration) > 0.0)
    }

    @Test func trailVideoWriterLossless() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let videoOut = tempDir.appendingPathComponent("test_lossless.mp4")

        let writer = try TrailVideoWriter(
            destinationURL: videoOut,
            sourceWidth: 64,
            sourceHeight: 64,
            fps: 30,
            quality: .lossless,
            format: .mp4,
            resolution: .source
        )

        for i in 0..<6 {
            let frame = Self.createSyntheticFrame(width: 64, height: 64, starX: 12 + i * 4, starY: 32)
            try writer.writeSnapshot(image: frame, repeats: 1)
        }

        let finalURL = try await writer.finish()
        #expect(FileManager.default.fileExists(atPath: finalURL.path))

        let asset = AVURLAsset(url: finalURL)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        #expect(tracks.count == 1)
    }

    @Test func trailVideoWriterMedium() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let videoOut = tempDir.appendingPathComponent("test_medium.mp4")

        let writer = try TrailVideoWriter(
            destinationURL: videoOut,
            sourceWidth: 64,
            sourceHeight: 64,
            fps: 30,
            quality: .medium,
            format: .mp4,
            resolution: .source
        )

        for i in 0..<6 {
            let frame = Self.createSyntheticFrame(width: 64, height: 64, starX: 12 + i * 4, starY: 32)
            try writer.writeSnapshot(image: frame, repeats: 1)
        }

        let finalURL = try await writer.finish()
        #expect(FileManager.default.fileExists(atPath: finalURL.path))

        let asset = AVURLAsset(url: finalURL)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        #expect(tracks.count == 1)
    }

    // MARK: - StackPipeline End-to-End Tests

    @Test func stackPipelineEndToEnd() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        var config = JobConfig(inputDirectory: tempDir, outputDirectory: tempDir)
        config.outputBaseName = "e2e_stack"
        config.videoEnabled = true
        config.videoFPS = 30
        config.saveFrames = true
        config.extensionFactor = 1.0

        let frameCount = 5
        var transforms: [FrameTransform] = []

        // Create transforms shifting by (+2, +1) each frame
        for i in 0..<frameCount {
            var t = FrameTransform()
            t.frameIndex = i
            t.tx = Double(i * 2)
            t.ty = Double(i * 1)
            t.time = Double(i * 30)
            transforms.append(t)
        }

        let crop = CropRegion(x: 10, y: 10, width: 60, height: 60)

        // Frame loader generating star at (30, 30)
        let loadFrame: @Sendable (Int) async throws -> PixelImage = { _ in
            Self.createSyntheticFrame(width: 80, height: 80, starX: 30, starY: 30, starRadius: 1)
        }

        nonisolated(unsafe) var progressUpdates: [Double] = []
        let result = try await StackPipeline.run(
            frameCount: frameCount,
            transforms: transforms,
            crop: crop,
            config: config,
            loadFrame: loadFrame,
            progress: { state in
                progressUpdates.append(state.progress)
            }
        )

        #expect(result.finalImage != nil)
        guard let finalImg = result.finalImage else { return }

        #expect(finalImg.width == 60)
        #expect(finalImg.height == 60)

        // Verify star trail: each frame i had star at (30, 30) in src.
        // Warped star in crop is at (30 + i * 2 - 10, 30 + i * 1 - 10) = (20 + 2*i, 20 + i)
        for i in 0..<frameCount {
            let px = 20 + i * 2
            let py = 20 + i * 1
            let idx = (py * 60 + px) * 3
            #expect(finalImg.data[idx] > 0.7)
        }

        // Verify video output
        #expect(result.videoURL != nil)
        if let videoURL = result.videoURL {
            #expect(FileManager.default.fileExists(atPath: videoURL.path))
            let asset = AVURLAsset(url: videoURL)
            let tracks = try await asset.loadTracks(withMediaType: .video)
            #expect(!tracks.isEmpty)
        }

        // Verify exported frames
        #expect(result.exportedFrameURLs.count == frameCount)
        let manifestURL = tempDir.appendingPathComponent("\(config.outputBaseName)_frames").appendingPathComponent("sequence.json")
        #expect(FileManager.default.fileExists(atPath: manifestURL.path))
    }

    @Test func stackPipelineCancellation() async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let config = JobConfig(inputDirectory: tempDir, outputDirectory: tempDir)
        let crop = CropRegion(x: 0, y: 0, width: 40, height: 40)

        let task = Task {
            try await StackPipeline.run(
                frameCount: 100,
                transforms: (0..<100).map { _ in FrameTransform() },
                crop: crop,
                config: config,
                loadFrame: { _ in
                    try await Task.sleep(nanoseconds: 50_000_000)
                    return Self.createSyntheticFrame(width: 40, height: 40, starX: 20, starY: 20)
                }
            )
        }

        task.cancel()

        do {
            _ = try await task.value
            #expect(Bool(false), "Pipeline should have thrown upon cancellation")
        } catch is CancellationError {
            #expect(Bool(true))
        } catch {
            #expect(Bool(true))
        }
    }
}
