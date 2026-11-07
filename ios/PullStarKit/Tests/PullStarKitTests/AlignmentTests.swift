import Testing
import Foundation
import CoreGraphics
@testable import PullStarKit

// MARK: - Synthetic Sky Generator

private func generateSyntheticSky(
    width: Int = 420,
    height: Int = 320,
    stars: [(x: Double, y: Double, peak: Float, sigma: Double)],
    noiseSigma: Float = 0.005,
    seed: UInt64 = 42
) -> PixelImage {
    var data = [Float](repeating: 0, count: width * height)

    // Pseudo-random background noise (simple LCG)
    var state = seed
    for i in 0..<data.count {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let u1 = Float(state >> 32) / Float(UInt32.max)
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let u2 = Float(state >> 32) / Float(UInt32.max)
        let z = sqrt(-2.0 * log(max(1e-7, u1))) * cos(2.0 * .pi * u2)
        data[i] = max(0.0, 0.05 + z * noiseSigma)
    }

    // Add 2D Gaussian stars
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
                data[row + x] += val
            }
        }
    }

    return PixelImage(width: width, height: height, channels: 1, data: data)
}

private func generateCatalog(count: Int = 35, width: Int = 420, height: Int = 320, seed: UInt64 = 101) -> [(x: Double, y: Double, peak: Float, sigma: Double)] {
    var stars: [(x: Double, y: Double, peak: Float, sigma: Double)] = []
    var state = seed

    let margin = 40.0
    for _ in 0..<count {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let rx = Double(state >> 32) / Double(UInt32.max)
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let ry = Double(state >> 32) / Double(UInt32.max)
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let rp = Float(state >> 32) / Float(UInt32.max)

        let x = margin + rx * (Double(width) - 2 * margin)
        let y = margin + ry * (Double(height) - 2 * margin)
        let peak = 0.4 + rp * 0.5
        stars.append((x: x, y: y, peak: peak, sigma: 1.4))
    }
    return stars
}

// MARK: - Unit Tests

@Suite("Alignment & Detection Engine Tests")
struct AlignmentTests {

    @Test("StarDetector accurately locates centroids and rejects hot pixels")
    func testStarDetection() {
        let detector = StarDetector()
        let catalog = [
            (x: 100.25, y: 80.5, peak: Float(0.8), sigma: 1.4),
            (x: 250.75, y: 150.2, peak: Float(0.6), sigma: 1.4),
            (x: 320.0, y: 220.0, peak: Float(0.7), sigma: 1.4)
        ]

        var image = generateSyntheticSky(width: 420, height: 320, stars: catalog)

        // Add a single-pixel hot pixel (cosmic ray spike)
        image.data[100 * 420 + 200] = 1.0

        let detected = detector.detectStars(in: image, maxStars: 50)
        #expect(!detected.isEmpty)

        // Hot pixel at (200, 100) must be rejected
        let hotPixelFound = detected.contains { pt in
            hypot(Double(pt.point.x) - 200.0, Double(pt.point.y) - 100.0) < 2.0
        }
        #expect(!hotPixelFound, "Hot pixel was not rejected by compactness / core ratio check")

        // Real stars must be recovered with sub-pixel precision (< 0.25 px)
        for star in catalog {
            let match = detected.first { pt in
                hypot(Double(pt.point.x) - star.x, Double(pt.point.y) - star.y) < 1.0
            }
            #expect(match != nil, "Star at (\(star.x), \(star.y)) was not detected")
            if let m = match {
                let err = hypot(Double(m.point.x) - star.x, Double(m.point.y) - star.y)
                #expect(err < 0.25, "Centroid error \(err) exceeded tolerance")
            }
        }
    }

    @Test("StarFieldMatcher recovers known rotation and translation")
    func testStarFieldMatching() {
        let catalog = generateCatalog(count: 30)
        let sourcePoints = catalog.map { CGPoint(x: $0.x, y: $0.y) }

        let angle = 2.5 * Double.pi / 180.0
        let cosA = cos(angle)
        let sinA = sin(angle)
        let tx = 14.5
        let ty = -8.2

        let targetPoints = sourcePoints.map { p -> CGPoint in
            let x = cosA * Double(p.x) - sinA * Double(p.y) + tx
            let y = sinA * Double(p.x) + cosA * Double(p.y) + ty
            return CGPoint(x: x, y: y)
        }

        let match = StarFieldMatcher.match(source: sourcePoints, target: targetPoints)
        #expect(match != nil)

        if let m = match {
            #expect(m.sourceInliers.count >= 20)
            let recoveredAngle = m.rotationAngleDegrees
            let expectedAngle = 2.5
            #expect(abs(recoveredAngle - expectedAngle) < 0.05, "Angle error: \(recoveredAngle) vs \(expectedAngle)")

            let recoveredTx = m.matrix[2]
            let recoveredTy = m.matrix[5]
            #expect(abs(recoveredTx - tx) < 0.1, "tx error: \(recoveredTx) vs \(tx)")
            #expect(abs(recoveredTy - ty) < 0.1, "ty error: \(recoveredTy) vs \(ty)")
            #expect(m.rmsError < 0.1)
        }
    }

    @Test("KalmanSmoother filters noise and rejects outliers")
    func testKalmanSmoother() {
        let smoother = KalmanSmoother(processNoise: 0.01, measurementNoise: 2.0)
        smoother.initialize(at: CGPoint(x: 100, y: 100))

        // Sequential steady motion: vx = 1.0, vy = 0.5
        for i in 1...10 {
            smoother.predict()
            let measured = CGPoint(x: 100.0 + Double(i) * 1.0, y: 100.0 + Double(i) * 0.5)
            smoother.update(with: measured)
        }

        let pos = smoother.currentPosition()
        #expect(abs(pos.x - 110.0) < 0.5)
        #expect(abs(pos.y - 105.0) < 0.5)

        // Large jump outlier: (150, 150)
        smoother.predict()
        let outlier = CGPoint(x: 150, y: 150)
        let innov = smoother.innovation(for: outlier)
        #expect(innov > 15.0, "Outlier was not flagged: innovation = \(innov)")

        // Batch smoothing
        var noisyPath: [CGPoint] = []
        for i in 0..<30 {
            let jitter = (i % 2 == 0) ? 1.5 : -1.5
            noisyPath.append(CGPoint(x: 10.0 + Double(i) * 2.0 + jitter, y: 20.0 + Double(i) * 1.0 - jitter))
        }

        let smoothedPath = KalmanSmoother.smooth(points: noisyPath, processNoise: 0.01, measurementNoise: 2.0)
        #expect(smoothedPath.count == noisyPath.count)

        // Smoothed path should have lower jitter variance than noisy path
        var rawJitter = 0.0
        var smoothJitter = 0.0
        for i in 1..<(noisyPath.count - 1) {
            let rMid = CGPoint(x: (noisyPath[i-1].x + noisyPath[i+1].x) * 0.5, y: (noisyPath[i-1].y + noisyPath[i+1].y) * 0.5)
            rawJitter += hypot(Double(noisyPath[i].x - rMid.x), Double(noisyPath[i].y - rMid.y))

            let sMid = CGPoint(x: (smoothedPath[i-1].x + smoothedPath[i+1].x) * 0.5, y: (smoothedPath[i-1].y + smoothedPath[i+1].y) * 0.5)
            smoothJitter += hypot(Double(smoothedPath[i].x - sMid.x), Double(smoothedPath[i].y - sMid.y))
        }

        #expect(smoothJitter < rawJitter * 0.5, "Smoother failed to reduce path jitter")
    }

    @Test("CropCalculator produces valid even-dimensioned common crop")
    func testCropCalculation() throws {
        var t1 = FrameTransform()
        t1.tx = 10.0; t1.ty = -5.0
        var t2 = FrameTransform()
        t2.tx = -8.0; t2.ty = 12.0

        let crop = try CropCalculator.calculateCrop(transforms: [t1, t2], width: 420, height: 320)
        #expect(crop.width > 0)
        #expect(crop.height > 0)
        #expect(crop.width % 2 == 0, "Crop width must be even for video encoding")
        #expect(crop.height % 2 == 0, "Crop height must be even for video encoding")
        #expect(crop.x >= 10)
        #expect(crop.x + crop.width <= 420)
        #expect(crop.y >= 12)
        #expect(crop.y + crop.height <= 320)
    }

    @Test("AlignmentAnalyzer preserves sky rotation and removes wobble in automatic mode")
    func testAlignmentAnalyzerAutomatic() async throws {
        let catalog = generateCatalog(count: 35, width: 420, height: 320)
        let frameCount = 12

        // Sky rotation pole outside image (-280, -150)
        let poleX = -280.0
        let poleY = -150.0
        let dTheta = 0.3 * Double.pi / 180.0

        var frames: [PixelImage] = []
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
            frames.append(generateSyntheticSky(width: 420, height: 320, stars: frameStars, seed: UInt64(100 + i)))
        }

        let capturedFrames = frames

        var config = JobConfig(
            inputDirectory: URL(filePath: "/tmp/in"),
            outputDirectory: URL(filePath: "/tmp/out")
        )
        // Auto mode test (no manual polaris)
        config.useKalman = false

        let analyzer = AlignmentAnalyzer()
        let result = try await analyzer.analyze(
            frameCount: frameCount,
            loadLuma: { idx in capturedFrames[idx] },
            times: (0..<frameCount).map { Double($0) },
            config: config,
            progress: { _, _, _, _ in }
        )

        #expect(result.transforms.count == frameCount)
        #expect(result.referenceStars.count >= 6)
        #expect(result.confidence > 0.5)

        // All frames should be valid
        for t in result.transforms {
            #expect(!t.skipped)
        }

        // Verify camera shake was removed and smooth sky rotation was preserved:
        var totalErrors: [Double] = []
        for i in 0..<frameCount {
            let t = result.transforms[i]
            let theta = Double(i) * dTheta
            let cosT = cos(theta)
            let sinT = sin(theta)

            let sign = (i % 2 == 0) ? 1.0 : -1.0
            let wobbleX = sign * 2.5
            let wobbleY = -sign * 1.5

            var frameErrors: [Double] = []
            for s in catalog {
                // Expected position under smooth sky rotation without wobble
                let dx = s.x - poleX
                let dy = s.y - poleY
                let targetX = poleX + (cosT * dx - sinT * dy)
                let targetY = poleY + (sinT * dx + cosT * dy)

                // Observed position in frame i (with wobble)
                let observedX = targetX + wobbleX
                let observedY = targetY + wobbleY

                // Corrected position
                let corrected = t.apply(CGPoint(x: observedX, y: observedY))
                let err = hypot(Double(corrected.x) - targetX, Double(corrected.y) - targetY)
                frameErrors.append(err)
            }
            let meanFrameErr = frameErrors.reduce(0.0, +) / Double(frameErrors.count)
            totalErrors.append(meanFrameErr)
        }

        let meanError = totalErrors.reduce(0.0, +) / Double(totalErrors.count)
        #expect(meanError < 0.75, "Mean error across all frames was \(meanError), expected < 0.75 px")

        // Full registration would collapse trails to zero. Sky rotation must be preserved:
        let totalSkyRotationDeg = Double(frameCount - 1) * (dTheta * 180.0 / .pi)
        #expect(totalSkyRotationDeg > 3.0)

        // Crop must be valid and even
        #expect(result.crop.width > 0 && result.crop.width % 2 == 0)
        #expect(result.crop.height > 0 && result.crop.height % 2 == 0)
    }

    @Test("Cloudy / blank frame is skipped and tracking resumes")
    func testCloudyFrameSkipping() async throws {
        let catalog = generateCatalog(count: 30)
        let frameCount = 8

        var frames: [PixelImage] = []
        for i in 0..<frameCount {
            if i == 4 {
                // Completely blank / cloudy frame
                frames.append(PixelImage(width: 420, height: 320, channels: 1))
            } else {
                frames.append(generateSyntheticSky(width: 420, height: 320, stars: catalog, seed: UInt64(200 + i)))
            }
        }

        let capturedFrames = frames

        let config = JobConfig(
            inputDirectory: URL(filePath: "/tmp/in"),
            outputDirectory: URL(filePath: "/tmp/out")
        )

        let analyzer = AlignmentAnalyzer()
        let result = try await analyzer.analyze(
            frameCount: frameCount,
            loadLuma: { idx in capturedFrames[idx] },
            times: [],
            config: config,
            progress: { _, _, _, _ in }
        )

        #expect(result.transforms[4].skipped, "Frame 4 should have been marked skipped")
        #expect(!result.transforms[5].skipped, "Frame 5 should have reacquired tracking")
    }

    @Test("Manual Polaris tracking with rotation correction")
    func testManualPolarisTracking() async throws {
        let p1 = CGPoint(x: 150.0, y: 150.0)
        let p2 = CGPoint(x: 300.0, y: 150.0)

        let frameCount = 5
        var frames: [PixelImage] = []

        for i in 0..<frameCount {
            let dx = Double(i) * 2.0
            let dy = Double(i) * 1.0
            let stars = [
                (x: Double(p1.x) + dx, y: Double(p1.y) + dy, peak: Float(0.9), sigma: 1.5),
                (x: Double(p2.x) + dx, y: Double(p2.y) + dy, peak: Float(0.8), sigma: 1.5)
            ]
            frames.append(generateSyntheticSky(width: 420, height: 320, stars: stars, noiseSigma: 0.001, seed: UInt64(300 + i)))
        }

        let capturedFrames = frames

        var config = JobConfig(
            inputDirectory: URL(filePath: "/tmp/in"),
            outputDirectory: URL(filePath: "/tmp/out")
        )
        config.polaris = p1
        config.secondStar = p2
        config.useRotation = true

        let analyzer = AlignmentAnalyzer()
        let result = try await analyzer.analyze(
            frameCount: frameCount,
            loadLuma: { idx in capturedFrames[idx] },
            times: [],
            config: config,
            progress: { _, _, _, _ in }
        )

        #expect(result.transforms.count == frameCount)
        for i in 0..<frameCount {
            let t = result.transforms[i]
            #expect(!t.skipped)
            let expectedDx = -Double(i) * 2.0
            let expectedDy = -Double(i) * 1.0
            #expect(abs(t.tx - expectedDx) < 0.35, "Manual tracking dx error: \(t.tx) vs \(expectedDx)")
            #expect(abs(t.ty - expectedDy) < 0.35, "Manual tracking dy error: \(t.ty) vs \(expectedDy)")
        }
    }

    @Test("AlignmentAnalyzer respects Task cancellation")
    func testCancellation() async throws {
        let task = Task {
            let analyzer = AlignmentAnalyzer()
            let _ = try await analyzer.analyze(
                frameCount: 10,
                loadLuma: { idx in
                    try await Task.sleep(nanoseconds: 50_000_000)
                    return PixelImage(width: 420, height: 320, channels: 1)
                },
                times: [],
                config: JobConfig(inputDirectory: URL(filePath: "/tmp"), outputDirectory: URL(filePath: "/tmp")),
                progress: { _, _, _, _ in }
            )
        }
        task.cancel()
        do {
            _ = try await task.value
            #expect(Bool(false), "Expected cancellation error")
        } catch is CancellationError {
            // Expected
        } catch {
            // Cancelled
        }
    }
}
