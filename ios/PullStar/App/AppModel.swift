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
            self.config = JobConfig(
                inputDirectory: defaultOutput,
                outputDirectory: defaultOutput
            )
        }

        self.engine = engine ?? EngineFactory.make()
        self.hardwareSummary = self.engine.computeInfo()

        // Restore bookmarks
        restoreSecurityScopedBookmarks()

        // If we restored a valid input folder, trigger an initial scan
        if FileManager.default.fileExists(atPath: config.inputDirectory.path) {
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
        (jobState.status == .completed && jobState.resultURL != nil) || jobState.resultURL != nil
    }

    public var exportMode: ExportMode {
        get { config.noStack ? .images : .trails }
        set {
            config.noStack = (newValue == .images)
            if newValue == .images {
                config.saveFrames = true
                if config.outputBaseName == "aligned_star_trails" || config.outputBaseName.hasSuffix(".tiff") {
                    config.outputBaseName = "aligned_images"
                }
            } else {
                if config.outputBaseName == "aligned_images" {
                    config.outputBaseName = "aligned_star_trails.tiff"
                }
            }
            persistSettings()
        }
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

    public func detectStars() {
        guard let ref = currentReferenceFrame, !isDetecting else { return }
        isDetecting = true
        detectionError = nil

        Task {
            do {
                let result = try await engine.detectStars(in: ref.url, config: config)
                self.jobState.detection = result
                if self.config.polaris == nil {
                    self.config.polaris = result.referenceStars.first
                }
                if self.config.secondStar == nil {
                    self.config.secondStar = result.secondStar
                }
                self.isDetecting = false
            } catch {
                self.detectionError = error.localizedDescription
                self.isDetecting = false
            }
        }
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
