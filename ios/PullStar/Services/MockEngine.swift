import Foundation
import UIKit
import CoreGraphics
import PullStarKit

/// Mock engine simulating star detection, alignment, and stacking for UI testing without real image processing libraries.
public final class MockEngine: PullStarEngine, @unchecked Sendable {
    public init() {}

    public func listSequence(in folder: URL, sortByTime: Bool) async throws -> [SequenceInfo] {
        // Sleep briefly to simulate directory scanning
        try await Task.sleep(nanoseconds: 400_000_000)

        // Try reading real files in the directory if accessible
        let fileManager = FileManager.default
        var realItems: [SequenceInfo] = []
        let supportedExtensions = Set(["jpg", "jpeg", "png", "tiff", "tif", "heic", "dng", "cr2", "cr3", "nef", "arw", "raw"])

        if let fileURLs = try? fileManager.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey], options: [.skipsHiddenFiles]) {
            for fileURL in fileURLs {
                let ext = fileURL.pathExtension.lowercased()
                if supportedExtensions.contains(ext) {
                    var info = SequenceInfo(url: fileURL, name: fileURL.lastPathComponent)
                    info.width = 4032
                    info.height = 3024
                    info.isRaw = ["dng", "cr2", "cr3", "nef", "arw", "raw"].contains(ext)
                    if let res = try? fileURL.resourceValues(forKeys: [.contentModificationDateKey]) {
                        info.captureDate = res.contentModificationDate
                    }
                    realItems.append(info)
                }
            }
        }

        if !realItems.isEmpty {
            if sortByTime {
                return realItems.sorted { ($0.captureDate ?? .distantPast) < ($1.captureDate ?? .distantPast) }
            } else {
                return realItems.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
            }
        }

        // Generate synthetic sequence for mock testing
        let baseDate = Date().addingTimeInterval(-3600)
        var synthetic: [SequenceInfo] = []
        for i in 1...24 {
            let name = String(format: "IMG_%04d.CR3", i)
            let fileURL = folder.appendingPathComponent(name)
            var info = SequenceInfo(url: fileURL, name: name)
            info.width = 4032
            info.height = 3024
            info.isRaw = true
            // Introduce an intentional timeline gap between frame 10 and 11
            let interval = (i > 10 ? Double(i + 3) : Double(i)) * 25.0
            info.captureDate = baseDate.addingTimeInterval(interval)
            synthetic.append(info)
        }

        if sortByTime {
            return synthetic.sorted { ($0.captureDate ?? .distantPast) < ($1.captureDate ?? .distantPast) }
        } else {
            return synthetic.sorted { $0.name < $1.name }
        }
    }

    public func preview(of url: URL, maxDimension: Int) async throws -> Data {
        // Return synthetic night sky image data with stars
        let targetWidth = min(maxDimension, 1024)
        let targetHeight = Int(Double(targetWidth) * 0.75)
        let size = CGSize(width: targetWidth, height: targetHeight)

        let renderer = UIGraphicsImageRenderer(size: size)
        let image = renderer.image { ctx in
            let cgCtx = ctx.cgContext

            // Sky gradient (deep cosmic blue to black)
            let colors = [
                UIColor(red: 0.02, green: 0.04, blue: 0.12, alpha: 1.0).cgColor,
                UIColor(red: 0.01, green: 0.01, blue: 0.03, alpha: 1.0).cgColor
            ] as CFArray
            let colorSpace = CGColorSpaceCreateDeviceRGB()
            if let gradient = CGGradient(colorsSpace: colorSpace, colors: colors, locations: [0.0, 1.0]) {
                cgCtx.drawRadialGradient(
                    gradient,
                    startCenter: CGPoint(x: size.width * 0.45, y: size.height * 0.4),
                    startRadius: 10,
                    endCenter: CGPoint(x: size.width * 0.5, y: size.height * 0.5),
                    endRadius: size.width * 0.7,
                    options: .drawsAfterEndLocation
                )
            }

            // Pseudo-random stars based on filename hash
            var seed = UInt64(abs(url.lastPathComponent.hashValue))
            func nextRandom() -> Double {
                seed = (seed &* 6364136223846793005) &+ 1442695040888963407
                return Double(seed % 10000) / 10000.0
            }

            // Foreground dark silhouette at bottom
            cgCtx.setFillColor(UIColor(red: 0.01, green: 0.01, blue: 0.02, alpha: 0.95).cgColor)
            cgCtx.move(to: CGPoint(x: 0, y: size.height))
            cgCtx.addLine(to: CGPoint(x: 0, y: size.height * 0.85))
            cgCtx.addLine(to: CGPoint(x: size.width * 0.35, y: size.height * 0.82))
            cgCtx.addLine(to: CGPoint(x: size.width * 0.7, y: size.height * 0.87))
            cgCtx.addLine(to: CGPoint(x: size.width, y: size.height * 0.84))
            cgCtx.addLine(to: CGPoint(x: size.width, y: size.height))
            cgCtx.closePath()
            cgCtx.fillPath()

            // Stars
            for _ in 0..<120 {
                let x = nextRandom() * Double(size.width)
                let y = nextRandom() * Double(size.height * 0.85)
                let radius = nextRandom() * 1.6 + 0.6
                let brightness = nextRandom() * 0.5 + 0.5
                cgCtx.setFillColor(UIColor(white: CGFloat(brightness), alpha: 0.9).cgColor)
                cgCtx.fillEllipse(in: CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2))
            }

            // Bright reference star (Polaris) near center
            let polX = size.width * 0.48
            let polY = size.height * 0.38
            cgCtx.setFillColor(UIColor(red: 0.85, green: 0.92, blue: 1.0, alpha: 1.0).cgColor)
            cgCtx.fillEllipse(in: CGRect(x: polX - 3.5, y: polY - 3.5, width: 7, height: 7))

            // Glow around Polaris
            cgCtx.setFillColor(UIColor(red: 0.6, green: 0.8, blue: 1.0, alpha: 0.25).cgColor)
            cgCtx.fillEllipse(in: CGRect(x: polX - 8, y: polY - 8, width: 16, height: 16))
        }

        guard let data = image.jpegData(compressionQuality: 0.85) else {
            throw NSError(domain: "MockEngine", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to render mock preview image"])
        }
        return data
    }

    public func detectStars(in url: URL, config: JobConfig) async throws -> DetectionResult {
        try await Task.sleep(nanoseconds: 600_000_000)
        let polaris = CGPoint(x: 1950, y: 1180)
        let secondStar = CGPoint(x: 2750, y: 1620)
        let referenceStars = [
            polaris,
            secondStar,
            CGPoint(x: 1240, y: 890),
            CGPoint(x: 3100, y: 950),
            CGPoint(x: 820, y: 1780),
            CGPoint(x: 2200, y: 2100)
        ]
        return DetectionResult(
            referenceImage: url,
            referenceStars: referenceStars,
            secondStar: secondStar,
            confidence: 0.96
        )
    }

    public func run(_ config: JobConfig) -> AsyncStream<JobState> {
        AsyncStream { continuation in
            let runTask = Task {
                var state = JobState()
                state.status = .running
                state.total = 24
                state.frameCount = 24
                state.computeDescription = self.computeInfo()

                func checkCancelled() -> Bool {
                    if Task.isCancelled {
                        state.status = .cancelling
                        continuation.yield(state)
                        state.status = .cancelled
                        continuation.yield(state)
                        continuation.finish()
                        return true
                    }
                    return false
                }

                // Stage 1: Preparation (~1.2s)
                state.stage = .preparation
                for step in 1...6 {
                    if checkCancelled() { return }
                    try? await Task.sleep(nanoseconds: 200_000_000)
                    state.progress = Double(step) / 6.0
                    state.overallProgress = state.progress * 0.12
                    continuation.yield(state)
                }

                // Stage 2: Conversion (if requested) (~1.5s)
                if config.conversionFormat != .none {
                    state.stage = .conversion
                    for frame in 1...state.total {
                        if checkCancelled() { return }
                        try? await Task.sleep(nanoseconds: 70_000_000)
                        state.current = frame
                        state.progress = Double(frame) / Double(state.total)
                        state.overallProgress = 0.12 + (state.progress * 0.15)
                        continuation.yield(state)
                    }
                }

                // Stage 3: Pass 1 Analysis & Alignment (~3.5s)
                state.stage = .pass1
                for frame in 1...state.total {
                    if checkCancelled() { return }
                    try? await Task.sleep(nanoseconds: 140_000_000)
                    state.current = frame
                    state.progress = Double(frame) / Double(state.total)
                    state.driftX = sin(Double(frame) * 0.25) * 1.8
                    state.driftY = cos(Double(frame) * 0.25) * 1.2
                    state.framesPerSecond = 21.4 + Double(frame % 3) * 0.5
                    let baseProgress = config.conversionFormat != .none ? 0.27 : 0.12
                    state.overallProgress = baseProgress + (state.progress * 0.35)
                    continuation.yield(state)
                }

                // Stage 4: Crop calculation (~0.8s)
                state.stage = .cropCalc
                for step in 1...4 {
                    if checkCancelled() { return }
                    try? await Task.sleep(nanoseconds: 200_000_000)
                    state.progress = Double(step) / 4.0
                    continuation.yield(state)
                }

                // Stage 5: Pass 2 Stacking & Trail Synthesis (~3.5s)
                state.stage = .pass2
                for frame in 1...state.total {
                    if checkCancelled() { return }
                    try? await Task.sleep(nanoseconds: 140_000_000)
                    state.current = frame
                    state.progress = Double(frame) / Double(state.total)
                    state.livePreviewRevision = frame
                    state.overallProgress = 0.65 + (state.progress * 0.25)
                    continuation.yield(state)
                }

                // Stage 6: Video rendering (if enabled) (~1.5s)
                if config.videoEnabled && !config.noStack {
                    state.stage = .videoRender
                    for step in 1...10 {
                        if checkCancelled() { return }
                        try? await Task.sleep(nanoseconds: 150_000_000)
                        state.progress = Double(step) / 10.0
                        state.overallProgress = 0.90 + (state.progress * 0.08)
                        continuation.yield(state)
                    }
                }

                // Finalize result image file
                let resultFile = self.generateMockResultImage(in: config.outputDirectory, baseName: config.outputBaseName, format: config.imageFormat)
                state.resultURL = resultFile
                state.stage = .done
                state.status = .completed
                state.progress = 1.0
                state.overallProgress = 1.0
                continuation.yield(state)
                continuation.finish()
            }

            continuation.onTermination = { @Sendable _ in
                runTask.cancel()
            }
        }
    }

    public func computeInfo() -> String {
        "Apple Silicon GPU & Metal 3 · Accelerate"
    }

    private func generateMockResultImage(in directory: URL, baseName: String, format: ImageFormat) -> URL {
        let ext = format == .tiff ? "tiff" : (format == .png ? "png" : "jpg")
        let filename = "\(baseName).\(ext)"
        let targetURL = directory.appendingPathComponent(filename)

        let size = CGSize(width: 1920, height: 1080)
        let renderer = UIGraphicsImageRenderer(size: size)
        let img = renderer.image { ctx in
            let cgCtx = ctx.cgContext
            // Deep sky gradient
            let colors = [
                UIColor(red: 0.01, green: 0.03, blue: 0.09, alpha: 1.0).cgColor,
                UIColor(red: 0.0, green: 0.0, blue: 0.02, alpha: 1.0).cgColor
            ] as CFArray
            let colorSpace = CGColorSpaceCreateDeviceRGB()
            if let gradient = CGGradient(colorsSpace: colorSpace, colors: colors, locations: [0.0, 1.0]) {
                cgCtx.drawRadialGradient(
                    gradient,
                    startCenter: CGPoint(x: size.width * 0.48, y: size.height * 0.38),
                    startRadius: 20,
                    endCenter: CGPoint(x: size.width * 0.5, y: size.height * 0.5),
                    endRadius: size.width * 0.8,
                    options: .drawsAfterEndLocation
                )
            }

            // Concentric circular star trails centered on Polaris
            let center = CGPoint(x: size.width * 0.48, y: size.height * 0.38)
            for r in stride(from: 40.0, to: 950.0, by: 12.0) {
                let startAngle = CGFloat(Double(Int(r * 17) % 360) * .pi / 180.0)
                let arcLength = CGFloat(Double(25 + Int(r * 3) % 45) * .pi / 180.0)
                let endAngle = startAngle + arcLength

                let path = UIBezierPath(arcCenter: center, radius: CGFloat(r), startAngle: startAngle, endAngle: endAngle, clockwise: true)
                let alpha = max(0.2, min(0.9, 1.0 - (r / 1000.0) * 0.5))
                let hue = CGFloat(Int(r * 7) % 60) / 360.0
                UIColor(hue: hue + 0.55, saturation: 0.3, brightness: 0.95, alpha: alpha).setStroke()
                path.lineWidth = (Int(r) % 5 == 0) ? 2.0 : 1.0
                path.stroke()
            }

            // Foreground tree silhouette
            cgCtx.setFillColor(UIColor(red: 0.01, green: 0.01, blue: 0.02, alpha: 1.0).cgColor)
            cgCtx.move(to: CGPoint(x: 0, y: size.height))
            cgCtx.addLine(to: CGPoint(x: 0, y: size.height * 0.82))
            cgCtx.addLine(to: CGPoint(x: size.width * 0.3, y: size.height * 0.78))
            cgCtx.addLine(to: CGPoint(x: size.width * 0.6, y: size.height * 0.85))
            cgCtx.addLine(to: CGPoint(x: size.width, y: size.height * 0.80))
            cgCtx.addLine(to: CGPoint(x: size.width, y: size.height))
            cgCtx.closePath()
            cgCtx.fillPath()
        }

        // Save image to disk
        if let data = img.jpegData(compressionQuality: 0.9) {
            try? data.write(to: targetURL)
        }
        return targetURL
    }
}
