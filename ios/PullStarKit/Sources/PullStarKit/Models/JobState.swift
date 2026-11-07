import Foundation
import CoreGraphics

public enum JobStatus: String, Codable, Sendable { case idle, created, running, cancelling, cancelled, completed, failed
    public var isActive: Bool { self == .created || self == .running || self == .cancelling }
    public var isTerminal: Bool { self == .completed || self == .cancelled || self == .failed }
}
public enum JobStage: String, Codable, Sendable { case preparation, conversion, pass1, cropCalc = "crop_calc", pass2, videoRender = "video_render", done }

/// Mirrors frontend/src/jobAction.ts `JobState`.
public struct JobState: Sendable, Equatable {
    public var status: JobStatus = .idle
    public var stage: JobStage?
    public var progress = 0.0            // 0...1 within stage
    public var overallProgress = 0.0     // 0...1
    public var current = 0
    public var total = 0
    public var driftX = 0.0
    public var driftY = 0.0
    public var framesPerSecond = 0.0
    public var resultURL: URL?
    public var framesDirectory: URL?
    public var frameCount = 0
    public var videoURL: URL?
    public var livePreviewURL: URL?
    public var livePreviewRevision = 0
    public var error: String?
    public var detection: DetectionResult?
    public var computeDescription = ""
    public init() {}
}

public struct DetectionResult: Sendable, Equatable {
    public var referenceImage: URL
    public var referenceStars: [CGPoint]
    public var secondStar: CGPoint?
    public var confidence: Double
    public init(referenceImage: URL, referenceStars: [CGPoint], secondStar: CGPoint? = nil, confidence: Double) {
        self.referenceImage = referenceImage; self.referenceStars = referenceStars; self.secondStar = secondStar; self.confidence = confidence
    }
}

public struct SequenceInfo: Sendable, Equatable, Identifiable {
    public var id: URL { url }
    public var url: URL
    public var name: String
    public var captureDate: Date?
    public var width = 0, height = 0
    public var isRaw = false
    public init(url: URL, name: String) { self.url = url; self.name = name }
}
