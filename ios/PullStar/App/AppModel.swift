import Foundation
import SwiftUI
import Observation
import PullStarKit

public enum WorkspaceView: String, CaseIterable, Sendable {
    case workspace = "workspace"
    case results = "results"
}

public enum ExportMode: String, CaseIterable, Sendable {
    case trails = "trails"
    case images = "images"
}

public enum VideoPlaybackMode: String, CaseIterable, Sendable {
    case slowmo = "slowmo"
    case hyperlapse = "hyperlapse"
}

@Observable
@MainActor
public final class AppModel {
    // MARK: - Core State
    public var config: JobConfig
    public var sequence: [SequenceInfo] = []
    public var selectedReferenceIndex: Int = 0
    public var jobState: JobState = JobState()
    public var engine: any PullStarEngine

    // UI state
    public var activeView: WorkspaceView = .workspace
    public var isScanning: Bool = false
    public var scanError: String? = nil
    public var gapCount: Int = 0
    public var isDetecting: Bool = false
    public var detectionError: String? = nil
    public var hardwareSummary: String = "Hardware is detected automatically."
    public var isTelemetryCollapsed: Bool = true
    public var hasInputFolder: Bool = false
    /// Stars matched by "Detect references" (source pixel coordinates of `detectionFrameIndex`).
    public var detectedStars: [CGPoint] = []
    public var detectionConfidence: Double? = nil
    public var detectionNotice: String? = nil
    private var detectTask: Task<Void, Never>? = nil

    // Compatibility aliases with Viewfinder
    public var selectedIndex: Int {
        get { selectedReferenceIndex }
        set { selectedReferenceIndex = newValue }
    }

    public var state: JobState {
        get { jobState }
        set { jobState = newValue }
    }

    // Security-scoped URLs tracking
    private var activeSecurityScopedURLs: Set<URL> = []

    // Background running task
    private var jobTask: Task<Void, Never>? = nil

    // Persistence keys
    private static let persistedConfigKey = "pullstar_persisted_job_config"
    private static let inputFolderBookmarkKey = "pullstar_input_folder_bookmark"
    private static let outputFolderBookmarkKey = "pullstar_output_folder_bookmark"
    private static let conversionFolderBookmarkKey = "pullstar_conversion_folder_bookmark"

    // MARK: - Initialization
    public init(engine: (any PullStarEngine)? = nil) {
        let defaultOutput = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())

        // Default or restored configuration
        if let data = UserDefaults.standard.data(forKey: Self.persistedConfigKey),
           let saved = try? JSONDecoder().decode(JobConfig.self, from: data) {
            self.config = saved
        } else {
            var fresh = JobConfig(inputDirectory: defaultOutput, outputDirectory: defaultOutput)
            fresh.outputBaseName = "aligned_star_trails.tiff"
            self.config = fresh
        }

        self.engine = engine ?? EngineFactory.make()
        self.hardwareSummary = self.engine.computeInfo()

        // Restore bookmarks
        restoreSecurityScopedBookmarks()

        // If we restored a valid input folder, trigger an initial scan
        if hasInputFolder && FileManager.default.fileExists(atPath: config.inputDirectory.path) {
            scanDirectory()
        }
    }

    // MARK: - Computed Properties
    public var isProcessing: Bool {
        jobState.status.isActive
    }

    public var isCancelling: Bool {
        jobState.status == .cancelling
    }

    public var hasResult: Bool {
        jobState.status == .completed && jobState.resultURL != nil
    }

    public var exportMode: ExportMode {
        get { config.noStack ? .images : .trails }
        set {
            config.noStack = (newValue == .images)
            if newValue == .images {
                config.saveFrames = true
                config.videoEnabled = false
                config.outputBaseName = "aligned_images"
            } else {
                config.outputBaseName = "aligned_star_trails.\(config.imageFormat.rawValue)"
            }
            persistSettings()
        }
    }

    /// Web: changing the image format rewrites the trail filename's extension.
    public var imageFormat: ImageFormat {
        get { config.imageFormat }
        set {
            config.imageFormat = newValue
            if exportMode == .trails {
                let name = config.outputBaseName
                let stem = (name as NSString).pathExtension.isEmpty ? name : (name as NSString).deletingPathExtension
                config.outputBaseName = "\(stem).\(newValue.rawValue)"
            }
            persistSettings()
        }
    }

    public var videoQuality: VideoQuality {
        get { config.quality }
        set { config.quality = newValue; if newValue == .prores { config.videoFormat = .mov }; persistSettings() }
    }

    public var videoFormat: VideoFormat {
        get { config.videoFormat == .auto ? .mp4 : config.videoFormat }
        set { config.videoFormat = newValue; if newValue == .mp4 && config.quality == .prores { config.quality = .high }; persistSettings() }
    }

    public var videoPlaybackMode: VideoPlaybackMode {
        get { config.videoHyperlapse ? .hyperlapse : .slowmo }
        set {
            config.videoHyperlapse = (newValue == .hyperlapse)
            persistSettings()
        }
    }

    public var minimumFrames: Int {
        exportMode == .images ? 3 : 10
    }

    public var isReady: Bool {
        !sequence.isEmpty &&
        sequence.count >= minimumFrames &&
        !config.outputBaseName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
        !isScanning &&
        !isDetecting
    }

    public var validationError: String? {
        config.validationError()
    }

    public var currentReferenceFrame: SequenceInfo? {
        guard !sequence.isEmpty, selectedReferenceIndex >= 0, selectedReferenceIndex < sequence.count else {
            return sequence.first
        }
        return sequence[selectedReferenceIndex]
    }

    // MARK: - Folder Selection & Security Bookmarks
    public func chooseFolder(_ url: URL) {
        guard url.startAccessingSecurityScopedResource() else { return }
        activeSecurityScopedURLs.insert(url)

        config.inputDirectory = url
        hasInputFolder = true
        config.polaris = nil
        config.secondStar = nil
        clearDetection()
        saveBookmark(for: url, key: Self.inputFolderBookmarkKey)
        persistSettings()

        scanDirectory()
    }

    public func chooseOutputFolder(_ url: URL) {
        guard url.startAccessingSecurityScopedResource() else { return }
        activeSecurityScopedURLs.insert(url)

        config.outputDirectory = url
        saveBookmark(for: url, key: Self.outputFolderBookmarkKey)
        persistSettings()
    }

    public func chooseConversionFolder(_ url: URL) {
        guard url.startAccessingSecurityScopedResource() else { return }
        activeSecurityScopedURLs.insert(url)

        config.conversionOutputDirectory = url
        saveBookmark(for: url, key: Self.conversionFolderBookmarkKey)
        persistSettings()
    }

    private func saveBookmark(for url: URL, key: String) {
        do {
            let bookmark = try url.bookmarkData(
                options: .minimalBookmark,
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            UserDefaults.standard.set(bookmark, forKey: key)
        } catch {
            print("Failed to create bookmark for \(url): \(error)")
        }
    }

    private func restoreSecurityScopedBookmarks() {
        // Input folder
        if let bookmarkData = UserDefaults.standard.data(forKey: Self.inputFolderBookmarkKey) {
            var isStale = false
            if let resolved = try? URL(resolvingBookmarkData: bookmarkData, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &isStale),
               resolved.startAccessingSecurityScopedResource() {
                activeSecurityScopedURLs.insert(resolved)
                config.inputDirectory = resolved
                hasInputFolder = true
            }
        }

        // Output folder
        if let bookmarkData = UserDefaults.standard.data(forKey: Self.outputFolderBookmarkKey) {
            var isStale = false
            if let resolved = try? URL(resolvingBookmarkData: bookmarkData, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &isStale),
               resolved.startAccessingSecurityScopedResource() {
                activeSecurityScopedURLs.insert(resolved)
                config.outputDirectory = resolved
            }
        }

        // Conversion folder
        if let bookmarkData = UserDefaults.standard.data(forKey: Self.conversionFolderBookmarkKey) {
            var isStale = false
            if let resolved = try? URL(resolvingBookmarkData: bookmarkData, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &isStale),
               resolved.startAccessingSecurityScopedResource() {
                activeSecurityScopedURLs.insert(resolved)
                config.conversionOutputDirectory = resolved
            }
        }
    }

    public func persistSettings() {
        if let data = try? JSONEncoder().encode(config) {
            UserDefaults.standard.set(data, forKey: Self.persistedConfigKey)
        }
    }

    // MARK: - Actions
    public func scanDirectory() {
        guard !isScanning, !isProcessing else { return }
        isScanning = true
        scanError = nil
        sequence = []
        gapCount = 0

        Task {
            do {
                let items = try await engine.listSequence(in: config.inputDirectory, sortByTime: config.sortByTime)
                self.sequence = items
                self.selectedReferenceIndex = 0
                self.clearDetection()
                if items.isEmpty { self.scanError = "No supported images were found in this folder." }

                // Detect gaps in timeline
                var gaps = 0
                if items.count > 1 {
                    for i in 1..<items.count {
                        if let d1 = items[i - 1].captureDate, let d2 = items[i].captureDate {
                            let diff = d2.timeIntervalSince(d1)
                            if diff > 60.0 { // Gap of more than 60s
                                gaps += 1
                            }
                        }
                    }
                }
                self.gapCount = gaps
                self.isScanning = false
            } catch {
                self.scanError = error.localizedDescription
                self.isScanning = false
            }
        }
    }

    public func clearDetection() {
        detectedStars = []
        detectionConfidence = nil
        detectionNotice = nil
    }

    /// Mirrors CelestialViewfinder.handleAutoDetect: matched stars are references,
    /// not an identification of Polaris, so Polaris is cleared.
    public func detectStars() {
        guard let first = sequence.first, !isDetecting, !isProcessing else {
            if sequence.isEmpty { detectionError = "Load a sequence before detecting stars." }
            return
        }
        isDetecting = true
        detectionError = nil
        clearDetection()

        detectTask = Task {
            do {
                let result = try await engine.detectStars(in: first.url, config: config)
                try Task.checkCancellation()
                self.config.polaris = nil
                self.jobState.detection = result
                self.detectedStars = result.referenceStars
                self.detectionConfidence = result.confidence
                if let second = result.secondStar { self.config.secondStar = second }
                if let idx = self.sequence.firstIndex(where: { $0.url == result.referenceImage }) {
                    self.selectedReferenceIndex = idx
                } else {
                    self.selectedReferenceIndex = 0
                }
            } catch is CancellationError {
                self.detectionNotice = "Star detection cancelled."
            } catch {
                self.detectionError = error.localizedDescription
            }
            self.isDetecting = false
            self.detectTask = nil
        }
    }

    public func cancelDetection() {
        detectTask?.cancel()
    }

    /// Changing the order invalidates the loaded sequence (web: setSortByTime).
    public func setSortByTime(_ value: Bool) {
        guard value != config.sortByTime else { return }
        config.sortByTime = value
        config.polaris = nil
        config.secondStar = nil
        clearDetection()
        persistSettings()
        if hasInputFolder { scanDirectory() }
    }

    public func pickReferenceStars(index: Int) {
        guard index >= 0 && index < sequence.count else { return }
        selectedReferenceIndex = index
        detectStars()
    }

    public func startJob() {
        guard !isProcessing else { return }
        if let error = config.validationError() {
            jobState.error = error
            jobState.status = .failed
            return
        }

        persistSettings()
        jobState = JobState()
        jobState.status = .running
        jobState.stage = .preparation
        activeView = .workspace
        jobState.total = sequence.count

        let currentConfig = config
        let activeEngine = engine

        jobTask = Task {
            let stream = activeEngine.run(currentConfig)
            for await updatedState in stream {
                if Task.isCancelled { break }
                self.jobState = updatedState
            }

            if self.jobState.status == .completed && self.jobState.resultURL != nil {
                // Switch to results view automatically
                self.activeView = .results
            }
        }
    }

    public func cancelJob() {
        guard isProcessing else { return }
        jobState.status = .cancelling
        jobTask?.cancel()
        jobTask = nil
    }

    public func loadPreview(for url: URL, maxDimension: Int = 1024) async throws -> Data {
        try await engine.preview(of: url, maxDimension: maxDimension)
    }
}
