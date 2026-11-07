import Foundation
import CoreGraphics

public enum Resolution: String, Codable, CaseIterable, Sendable { case source, k4 = "4k", k2 = "2k", p1080 = "1080p", p720 = "720p" }
public enum VideoQuality: String, Codable, CaseIterable, Sendable { case high, medium, lossless, prores, hevc }
public enum VideoFormat: String, Codable, CaseIterable, Sendable { case auto, mp4, mov }
public enum ImageFormat: String, Codable, CaseIterable, Sendable { case tiff, png, jpg }
public enum ComputeBackend: String, Codable, CaseIterable, Sendable { case auto, cpu, gpu }
public enum ConversionFormat: String, Codable, CaseIterable, Sendable { case none, jpg, tiff }

/// Mirrors backend/api/router.py `JobCreateRequest`. Paths are file URLs inside the app sandbox / security-scoped folders.
public struct JobConfig: Codable, Sendable, Equatable {
    public var inputDirectory: URL
    public var outputDirectory: URL
    public var outputBaseName = "aligned_output"
    public var extensionFactor = 1.0          // 1...5
    public var tailTaperStrength = 0.0        // 0...1
    public var tailAngleThreshold = 0.0       // 0...360
    public var useRotation = false
    public var useKalman = true
    public var kalmanProcessNoise = 0.01
    public var kalmanMeasurementNoise = 2.0
    public var ghostFramesPerReal = 10
    public var syntheticFadeFactor = 0.2
    public var useForegroundMask = true
    public var fillGaps = false
    public var videoEnabled = false
    public var videoFPS = 30                  // 1...120
    public var videoSlowdown = 1              // 1...8
    public var imageResolution = Resolution.source
    public var videoResolution = Resolution.source
    public var quality = VideoQuality.high
    public var videoFormat = VideoFormat.auto
    public var imageFormat = ImageFormat.tiff
    public var videoHyperlapse = false
    public var saveFrames = false
    public var noStack = false
    public var useCheckpoint = true
    public var resume = false
    public var sortByTime = true
    public var blendMode = "lighten"
    public var polaris: CGPoint?
    public var secondStar: CGPoint?
    public var computeBackend = ComputeBackend.auto
    public var cpuWorkers: Int?
    public var rawNoiseReduction = true
    public var rawExposureEV = 0.0           // 0...3
    public var conversionFormat = ConversionFormat.none
    public var conversionOutputDirectory: URL?

    public init(inputDirectory: URL, outputDirectory: URL) {
        self.inputDirectory = inputDirectory
        self.outputDirectory = outputDirectory
    }

    /// Same rules as the backend `validate_export`. Returns a user-facing message or nil.
    public func validationError() -> String? {
        if noStack && !saveFrames { return "Images-only export requires aligned images to be saved." }
        if noStack && videoEnabled { return "Trail video requires trail creation." }
        if videoEnabled && quality == .prores && videoFormat == .mp4 { return "ProRes requires a MOV container." }
        if useRotation && polaris != nil && secondStar == nil { return "Manual rotation correction requires a second reference star." }
        return nil
    }
}
