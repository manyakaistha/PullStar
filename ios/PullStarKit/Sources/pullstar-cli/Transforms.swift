import Foundation
import PullStarKit

struct DumpTransformOutput: Encodable {
    var frame: Int
    var a: Double
    var b: Double
    var tx: Double
    var c: Double
    var d: Double
    var ty: Double
    var time: Double
    var skipped: Bool
}

/// Pass-1 transform dump. Runs pass 1 via AlignmentAnalyzer and writes JSON.
func dumpTransforms(input: URL, output: URL) async throws {
    let fullSequence = try await SequenceLister.listSequence(in: input, sortByTime: true)
    let sequence = fullSequence.filter { info in
        let name = info.url.lastPathComponent
        return !name.hasSuffix(".live.jpg") && !name.hasPrefix(".")
    }

    guard !sequence.isEmpty else {
        throw IOError.cannotDecodeImage(input, reason: "No valid images found in sequence directory")
    }

    let baseDate = sequence.first?.captureDate
    let times: [Double] = sequence.map { info in
        if let d = info.captureDate, let b = baseDate {
            return d.timeIntervalSince(b)
        }
        return -1.0
    }

    let config = JobConfig(inputDirectory: input, outputDirectory: output.deletingLastPathComponent())
    let analyzer = AlignmentAnalyzer()
    let result = try await analyzer.analyze(
        frameCount: sequence.count,
        loadLuma: { idx in
            let url = sequence[idx].url
            return try ImageDecoder.decodeLuma(
                from: url,
                rawNoiseReduction: config.rawNoiseReduction,
                rawExposureEV: config.rawExposureEV
            )
        },
        times: times,
        config: config,
        progress: { _, _, _, _ in }
    )

    let outList = result.transforms.map { t in
        DumpTransformOutput(
            frame: t.frameIndex,
            a: t.a,
            b: t.b,
            tx: t.tx,
            c: t.c,
            d: t.d,
            ty: t.ty,
            time: t.time,
            skipped: t.skipped
        )
    }

    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted]
    let data = try encoder.encode(outList)
    try data.write(to: output)
    print("Dumped \(outList.count) transforms to \(output.path)")
}
