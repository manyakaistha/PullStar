import Foundation
import PullStarKit

// Developer CLI for exercising the engine on real frames without the app.
//   swift run -c release pullstar-cli run <inputDir> <outputDir> [--video] [--cpu]
//       Full job via PullStarEngineImpl; prints per-stage wall-clock timings.
//   swift run -c release pullstar-cli transforms <inputDir> <out.json>
//       Pass-1 only; writes per-frame transforms (see Transforms.swift).

let args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 3 else {
    print("usage: pullstar-cli run <input> <output> [--video] [--cpu] | transforms <input> <out.json>")
    exit(64)
}

switch args[0] {
case "run":
    var config = JobConfig(inputDirectory: URL(fileURLWithPath: args[1]), outputDirectory: URL(fileURLWithPath: args[2]))
    config.outputBaseName = "trails.tiff"
    config.videoEnabled = args.contains("--video")
    if args.contains("--cpu") { config.computeBackend = .cpu }
    try? FileManager.default.createDirectory(at: config.outputDirectory, withIntermediateDirectories: true)
    let engine = PullStarEngineImpl()
    print("compute:", engine.computeInfo())
    let start = Date()
    var stageStart = Date()
    var lastStage: JobStage?
    var final = JobState()
    for await state in engine.run(config) {
        if state.stage != lastStage {
            if let lastStage { print(String(format: "  %-12@ %6.1fs", lastStage.rawValue, Date().timeIntervalSince(stageStart))) }
            lastStage = state.stage
            stageStart = Date()
        }
        final = state
    }
    print(String(format: "total %.1fs  status=%@  drift=(%.3f, %.3f)", Date().timeIntervalSince(start), final.status.rawValue, final.driftX, final.driftY))
    if let e = final.error { print("error:", e) }
    print("result:", final.resultURL?.path ?? "-", " video:", final.videoURL?.path ?? "-")
    exit(final.status == .completed ? 0 : 1)
case "transforms":
    try await dumpTransforms(input: URL(fileURLWithPath: args[1]), output: URL(fileURLWithPath: args[2]))
default:
    print("unknown command \(args[0])"); exit(64)
}
