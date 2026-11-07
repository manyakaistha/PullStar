#if DEBUG || PULLSTAR_HARNESS
import SwiftUI
import UIKit
import PullStarKit

/// Debug-only visual check: drives the app into a given state, snapshots the window to PNG and exits.
///   PULLSTAR_SNAPSHOT=<dir>  PULLSTAR_SNAPSHOT_STATE=empty|loaded|references|running|results
///   PULLSTAR_SNAPSHOT_SIZE=1180x820
@MainActor
enum SnapshotHarness {
    static func runIfRequested(_ model: AppModel) async {
        let env = ProcessInfo.processInfo.environment
        guard let rawDir = env["PULLSTAR_SNAPSHOT"] else { return }
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        // Relative paths resolve inside the app's Documents folder (needed on device).
        func resolve(_ path: String) -> URL { path.hasPrefix("/") ? URL(fileURLWithPath: path) : docs.appendingPathComponent(path) }
        let dir = resolve(rawDir).path
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let state = env["PULLSTAR_SNAPSHOT_STATE"] ?? "empty"
        let dims = (env["PULLSTAR_SNAPSHOT_SIZE"] ?? "1180x820").split(separator: "x").compactMap { Double($0) }
        let size = CGSize(width: dims.first ?? 1180, height: dims.last ?? 820)

        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene {
            scene.sizeRestrictions?.minimumSize = size
            scene.sizeRestrictions?.maximumSize = size
        }
        try? await Task.sleep(for: .seconds(1))

        if let input = env["PULLSTAR_SNAPSHOT_INPUT"] {
            // Real-engine end-to-end run on a folder of frames.
            model.config.inputDirectory = resolve(input)
            model.config.outputDirectory = resolve(env["PULLSTAR_SNAPSHOT_OUTPUT"] ?? NSTemporaryDirectory())
            try? FileManager.default.createDirectory(at: model.config.outputDirectory, withIntermediateDirectories: true)
            model.config.videoEnabled = env["PULLSTAR_SNAPSHOT_VIDEO"] != nil
            model.hasInputFolder = true
            model.scanDirectory()
            while model.isScanning { try? await Task.sleep(for: .milliseconds(200)) }
            print("[harness] frames:", model.sequence.count, model.scanError ?? "")
            model.isTelemetryCollapsed = false
            model.startJob()
            var midShot = false
            let started = Date()
            while model.isProcessing && Date().timeIntervalSince(started) < 900 {
                try? await Task.sleep(for: .seconds(1))
                let line = "\(Int(Date().timeIntervalSince(started)))s \(model.jobState.stage?.rawValue ?? "-") \(String(format: "%.2f", model.jobState.overallProgress)) drift \(String(format: "%.2f,%.2f", model.jobState.driftX, model.jobState.driftY))\n"
                if let h = FileHandle(forWritingAtPath: dir + "/progress.log") { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
                else { try? line.write(toFile: dir + "/progress.log", atomically: true, encoding: .utf8) }
                print("[harness]", model.jobState.stage?.rawValue ?? "-", String(format: "%.2f", model.jobState.overallProgress),
                      "drift", model.jobState.driftX, model.jobState.driftY, "rev", model.jobState.livePreviewRevision)
                if !midShot, model.jobState.stage == .pass2, model.jobState.livePreviewRevision > 2 {
                    midShot = true
                    try? await Task.sleep(for: .seconds(1))
                    snapshot(dir: dir, name: "real-running", size: size)
                }
            }
            let summary = "status=\(model.jobState.status.rawValue) error=\(model.jobState.error ?? "-") result=\(model.jobState.resultURL?.lastPathComponent ?? "-") video=\(model.jobState.videoURL?.lastPathComponent ?? "-") frames=\(model.sequence.count) elapsed=\(Int(Date().timeIntervalSince(started)))s compute=\(model.jobState.computeDescription)\n"
            try? summary.write(toFile: dir + "/summary.txt", atomically: true, encoding: .utf8)
            print("[harness] final:", model.jobState.status.rawValue, model.jobState.error ?? "", model.jobState.resultURL?.path ?? "", model.jobState.videoURL?.path ?? "",
                  "elapsed", Int(Date().timeIntervalSince(started)))
            try? await Task.sleep(for: .seconds(3))
            snapshot(dir: dir, name: "real-result", size: size)
            exit(0)
        }

        if state != "empty" {
            model.config.inputDirectory = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("Night sky · Spiti")
            model.hasInputFolder = true
            model.scanDirectory()
            try? await Task.sleep(for: .seconds(2.5))
        }
        switch state {
        case "references":
            model.config.polaris = CGPoint(x: 1900, y: 1300)
            model.config.secondStar = CGPoint(x: 2600, y: 1800)
            model.isTelemetryCollapsed = false
        case "running":
            var s = JobState()
            s.status = .running; s.stage = .pass2; s.progress = 0.68; s.overallProgress = 0.80
            s.current = 48; s.total = 70; s.framesPerSecond = 24.2; s.driftX = 0.42; s.driftY = -0.18
            s.computeDescription = "Apple M4 GPU · 10 CPU workers"
            model.jobState = s
            model.isTelemetryCollapsed = false
            for i in 0..<30 {
                model.jobState.driftX = sin(Double(i) / 3) * 0.6; model.jobState.driftY = cos(Double(i) / 4) * 0.4
                try? await Task.sleep(for: .milliseconds(20))
            }
        case "results":
            let out = FileManager.default.temporaryDirectory.appendingPathComponent("aligned_star_trails.jpg")
            if let first = model.sequence.first, let data = try? await model.loadPreview(for: first.url, maxDimension: 2048) {
                try? data.write(to: out)
            }
            var s = JobState()
            s.status = .completed; s.stage = .done; s.progress = 1; s.overallProgress = 1
            s.resultURL = out
            model.jobState = s
            model.activeView = .results
        default: break
        }
        try? await Task.sleep(for: .seconds(2))

        snapshot(dir: dir, name: state, size: size)
        exit(0)
    }

    static func snapshot(dir: String, name: String, size: CGSize) {
        guard let window = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow }).first else { return }
        let renderer = UIGraphicsImageRenderer(bounds: window.bounds)
        let image = renderer.image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        let file = URL(fileURLWithPath: dir).appendingPathComponent("\(name)-\(Int(size.width))x\(Int(size.height)).png")
        try? image.pngData()?.write(to: file)
    }
}
#endif
