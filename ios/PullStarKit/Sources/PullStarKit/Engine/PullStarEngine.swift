import Foundation

/// The single seam between UI and processing. The UI only talks to this protocol.
/// `PullStarEngineImpl` (Engine/PullStarEngineImpl.swift) is the real implementation.
public protocol PullStarEngine: Sendable {
    /// Enumerate supported images (JPEG/PNG/TIFF/HEIC/RAW-DNG etc.) in a folder, sorted per `sortByTime`.
    func listSequence(in folder: URL, sortByTime: Bool) async throws -> [SequenceInfo]
    /// Downscaled preview image (max pixel dimension `maxDimension`) as JPEG data; RAW decoded via Core Image.
    func preview(of url: URL, maxDimension: Int) async throws -> Data
    /// Detect reference stars in the reference frame (automatic mode helper for the viewfinder).
    func detectStars(in url: URL, config: JobConfig) async throws -> DetectionResult
    /// Run a full job. The stream yields state updates and finishes after a terminal state. Cancelling the consuming Task cancels the job.
    func run(_ config: JobConfig) -> AsyncStream<JobState>
    /// Hardware description for the Processing hardware UI.
    func computeInfo() -> String
}
