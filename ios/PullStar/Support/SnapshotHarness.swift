#if DEBUG
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
        guard let dir = env["PULLSTAR_SNAPSHOT"] else { return }
        let state = env["PULLSTAR_SNAPSHOT_STATE"] ?? "empty"
        let dims = (env["PULLSTAR_SNAPSHOT_SIZE"] ?? "1180x820").split(separator: "x").compactMap { Double($0) }
        let size = CGSize(width: dims.first ?? 1180, height: dims.last ?? 820)

        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene {
            scene.sizeRestrictions?.minimumSize = size
            scene.sizeRestrictions?.maximumSize = size
        }
        try? await Task.sleep(for: .seconds(1))

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

        guard let window = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow }).first else { exit(2) }
        let renderer = UIGraphicsImageRenderer(bounds: window.bounds)
        let image = renderer.image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        let file = URL(fileURLWithPath: dir).appendingPathComponent("\(state)-\(Int(size.width))x\(Int(size.height)).png")
        try? image.pngData()?.write(to: file)
        exit(0)
    }
}
#endif
