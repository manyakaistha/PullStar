import Foundation
import CoreGraphics

/// Top-level coordinator for Pass 1 (Analysis).
///
/// Dispatches to automatic star field matching or manual Polaris/second-star tracking,
/// handles bounded-worker concurrent frame loading and detection, fits the sky-rotation-preserving
/// field trajectory, and computes the common valid crop region.
public final class AlignmentAnalyzer: Sendable {
    public init() {}

    /// Sequence times normalized by median exposure interval, matching Python sequence_times.
    public static func sequenceTimes(from times: [Double], frameCount: Int) -> [Double] {
        guard times.count == frameCount, frameCount > 1 else {
            return (0..<frameCount).map { Double($0) }
        }
        for i in 0..<frameCount {
            guard times[i] >= 0 else {
                return (0..<frameCount).map { Double($0) }
            }
        }
        var intervals: [Double] = []
        intervals.reserveCapacity(frameCount - 1)
        for i in 1..<frameCount {
            let dt = times[i] - times[i - 1]
            guard dt > 0 else {
                return (0..<frameCount).map { Double($0) }
            }
            intervals.append(dt)
        }
        let sortedIntervals = intervals.sorted()
        let median = sortedIntervals[sortedIntervals.count / 2]
        guard median >= 1.0 else {
            return (0..<frameCount).map { Double($0) }
        }
        var result = [0.0]
        var cumsum = 0.0
        for dt in intervals {
            cumsum += dt
            result.append(cumsum / median)
        }
        return result
    }

    /// Analyze a sequence of exposures to calculate per-frame alignment transforms and crop region.
    public func analyze(
        frameCount: Int,
        loadLuma: @escaping @Sendable (Int) async throws -> PixelImage,
        times: [Double],
        config: JobConfig,
        progress: @Sendable (Int, Int, Double /*driftX*/, Double /*driftY*/) -> Void
    ) async throws -> (
        transforms: [FrameTransform],
        crop: CropRegion,
        referenceStars: [CGPoint],
        confidence: Double
    ) {
        try Task.checkCancellation()

        if let polaris = config.polaris {
            return try await analyzeManual(
                frameCount: frameCount,
                loadLuma: loadLuma,
                times: times,
                config: config,
                initialPolaris: polaris,
                initialSecondStar: config.secondStar,
                progress: progress
            )
        } else {
            return try await analyzeAutomatic(
                frameCount: frameCount,
                loadLuma: loadLuma,
                times: times,
                config: config,
                progress: progress
            )
        }
    }

    // MARK: - Automatic Field Alignment

    private func analyzeAutomatic(
        frameCount: Int,
        loadLuma: @escaping @Sendable (Int) async throws -> PixelImage,
        times: [Double],
        config: JobConfig,
        progress: @Sendable (Int, Int, Double, Double) -> Void
    ) async throws -> (
        transforms: [FrameTransform],
        crop: CropRegion,
        referenceStars: [CGPoint],
        confidence: Double
    ) {
        guard frameCount >= 3 else {
            throw AlignmentError.notEnoughExposures("Automatic trail alignment needs at least three exposures.")
        }

        let workers = max(1, config.cpuWorkers ?? ProcessInfo.processInfo.activeProcessorCount)

        // 1. Concurrently extract star centroids for each frame using bounded TaskGroup
        struct FrameField: Sendable {
            var index: Int
            var stars: [CGPoint]
            var width: Int
            var height: Int
        }

        var fieldsDict = [Int: FrameField]()
        fieldsDict.reserveCapacity(frameCount)

        try await withThrowingTaskGroup(of: FrameField.self) { group in
            var submitted = 0
            let initialCount = min(workers, frameCount)

            for _ in 0..<initialCount {
                let idx = submitted
                submitted += 1
                group.addTask {
                    try Task.checkCancellation()
                    let img = try await loadLuma(idx)
                    try Task.checkCancellation()
                    let detected = StarDetector().detectStarPoints(
                        in: img,
                        maxStars: 100,
                        noisyRawRecovery: config.rawNoiseReduction
                    )
                    return FrameField(index: idx, stars: detected, width: img.width, height: img.height)
                }
            }

            for try await field in group {
                try Task.checkCancellation()
                fieldsDict[field.index] = field

                if submitted < frameCount {
                    let nextIdx = submitted
                    submitted += 1
                    group.addTask {
                        try Task.checkCancellation()
                        let img = try await loadLuma(nextIdx)
                        try Task.checkCancellation()
                        let detected = StarDetector().detectStarPoints(
                            in: img,
                            maxStars: 100,
                            noisyRawRecovery: config.rawNoiseReduction
                        )
                        return FrameField(index: nextIdx, stars: detected, width: img.width, height: img.height)
                    }
                }
            }
        }

        try Task.checkCancellation()

        // Verify consistent dimensions
        guard let firstField = fieldsDict[0] else {
            throw AlignmentError.trackingFailed("Failed to load first frame.")
        }
        let imageWidth = firstField.width
        let imageHeight = firstField.height

        for i in 1..<frameCount {
            if let f = fieldsDict[i], f.width != imageWidth || f.height != imageHeight {
                throw AlignmentError.dimensionMismatch("Frame dimensions differ at index \(i): \(f.width)x\(f.height) vs \(imageWidth)x\(imageHeight)")
            }
        }

        // 2. Sequential field matching
        var observations = [[Double]?](repeating: nil, count: frameCount)
        var confidences = [Double](repeating: 0.0, count: frameCount)
        var isValid = [Bool](repeating: false, count: frameCount)

        var referenceField: [CGPoint]?
        var previousField: [CGPoint]?
        var previousMatrix: [Double] = [
            1, 0, 0,
            0, 1, 0,
            0, 0, 1
        ]
        var referenceStars: [CGPoint] = []

        for index in 0..<frameCount {
            try Task.checkCancellation()
            let points = fieldsDict[index]?.stars ?? []

            var matrix: [Double]?
            var conf = 0.0

            if referenceField == nil && points.count >= StarFieldMatcher.minMatches {
                referenceField = points
                previousField = points
                referenceStars = points
                matrix = [
                    1, 0, 0,
                    0, 1, 0,
                    0, 0, 1
                ]
                conf = 1.0
            } else if let ref = referenceField {
                // Match against reference field directly to eliminate accumulated drift
                var match = StarFieldMatcher.match(source: ref, target: points)
                if let m = match {
                    matrix = m.matrix
                    conf = m.confidence
                    print("SWIFT \(index): MATCHED REF inliers=\(m.sourceInliers.count) rms=\(m.rmsError) tx=\(m.matrix[2]) ty=\(m.matrix[5]) rot=\(atan2(m.matrix[3], m.matrix[0]) * 180.0 / .pi)")
                } else if let prev = previousField {
                    // Fallback to previous frame if scene moved beyond original field
                    match = StarFieldMatcher.match(source: prev, target: points)
                    if let m = match {
                        matrix = FieldAnalysisModel.multiply3x3(m.matrix, previousMatrix)
                        conf = m.confidence
                        print("SWIFT \(index): MATCHED PREV inliers=\(m.sourceInliers.count) rms=\(m.rmsError) prev_tx=\(m.matrix[2]) prev_ty=\(m.matrix[5]) res_tx=\(matrix![2]) res_ty=\(matrix![5]) rot=\(atan2(matrix![3], matrix![0]) * 180.0 / .pi)")
                    } else {
                        print("SWIFT \(index): FAILED")
                    }
                }
            }

            let valid = (matrix != nil)
            isValid[index] = valid
            observations[index] = matrix
            confidences[index] = conf

            if valid, let mat = matrix {
                previousField = points
                previousMatrix = mat
            }
            progress(index + 1, frameCount, 0.0, 0.0)
        }

        let validIndices = (0..<frameCount).filter { isValid[$0] }
        let requiredValid = max(3, Int(ceil(Double(frameCount) / 2.0)))
        guard validIndices.count >= requiredValid else {
            throw AlignmentError.notEnoughMatches("Not enough reliable star matches. At least six visible stars must match in half the exposures; check focus, clouds, and sequence overlap.")
        }

        try Task.checkCancellation()

        // 3. Robust Sky-Rotation-Preserving Trajectory Fitting
        let normTimes = Self.sequenceTimes(from: times, frameCount: frameCount)
        let span = max(normTimes.last ?? 1.0, 1.0)
        let tValid = validIndices.map { normTimes[$0] / span }

        let observedAngles = validIndices.map { idx -> Double in
            let m = observations[idx]!
            return atan2(m[3], m[0])
        }
        let unwrappedAngles = FieldAnalysisModel.unwrapAngles(observedAngles)

        let designAngle = tValid.map { [1.0, $0] }
        let angleCoeffs = FieldAnalysisModel.robustFit(design: designAngle, values: unwrappedAngles, noise: 0.002)

        let curved = abs(angleCoeffs[1]) >= (0.1 * .pi / 180.0) && tValid.count >= 6
        let designTrans = tValid.map { FieldAnalysisModel.translationBasis(t: $0, angularSpeed: angleCoeffs[1], curved: curved) }

        let obsTx = validIndices.map { observations[$0]![2] }
        let obsTy = validIndices.map { observations[$0]![5] }

        let coeffsX = FieldAnalysisModel.robustFit(design: designTrans, values: obsTx, noise: 2.0)
        let coeffsY = FieldAnalysisModel.robustFit(design: designTrans, values: obsTy, noise: 2.0)

        let model = FieldAnalysisModel(
            angleCoefficients: angleCoeffs,
            translationCoeffsX: coeffsX,
            translationCoeffsY: coeffsY,
            timeSpan: span,
            curved: curved
        )

        // 4. Calculate per-frame correction transforms
        var transforms: [FrameTransform] = []
        transforms.reserveCapacity(frameCount)

        for i in 0..<frameCount {
            try Task.checkCancellation()
            var transform = FrameTransform()
            transform.frameIndex = i
            transform.time = normTimes[i]

            if isValid[i], let obsM = observations[i], let invObs = FieldAnalysisModel.invert3x3Affine(obsM) {
                let smoothM = model.motionAt(time: normTimes[i])
                let correction = FieldAnalysisModel.multiply3x3(smoothM, invObs)

                transform.a = correction[0]
                transform.b = correction[1]
                transform.tx = correction[2]
                transform.c = correction[3]
                transform.d = correction[4]
                transform.ty = correction[5]
                transform.skipped = false
            } else {
                transform.skipped = true
            }

            transforms.append(transform)
        }

        // Report tracking precision drift residuals matching alignment_engine.py track_cb
        for transform in transforms where !transform.skipped {
            progress(frameCount, frameCount, transform.tx, transform.ty)
        }

        // 5. Common crop calculation
        let crop = try CropCalculator.calculateCrop(transforms: transforms, width: imageWidth, height: imageHeight)

        // 6. Overall confidence
        let totalConf = validIndices.reduce(0.0) { $0 + confidences[$1] }
        let avgConf = totalConf / Double(validIndices.count)

        return (transforms, crop, referenceStars, avgConf)
    }

    // MARK: - Manual Reference Tracking

    private func analyzeManual(
        frameCount: Int,
        loadLuma: @escaping @Sendable (Int) async throws -> PixelImage,
        times: [Double],
        config: JobConfig,
        initialPolaris: CGPoint,
        initialSecondStar: CGPoint?,
        progress: @Sendable (Int, Int, Double, Double) -> Void
    ) async throws -> (
        transforms: [FrameTransform],
        crop: CropRegion,
        referenceStars: [CGPoint],
        confidence: Double
    ) {
        guard frameCount >= 1 else {
            throw AlignmentError.notEnoughExposures("Manual alignment needs at least one exposure.")
        }

        let detector = StarDetector()
        let useKalman = config.useKalman
        let useRotation = config.useRotation && initialSecondStar != nil

        let polarisKalman: KalmanSmoother? = useKalman ? KalmanSmoother(
            processNoise: config.kalmanProcessNoise,
            measurementNoise: config.kalmanMeasurementNoise
        ) : nil
        polarisKalman?.initialize(at: initialPolaris)

        let secondKalman: KalmanSmoother? = (useKalman && useRotation && initialSecondStar != nil) ? KalmanSmoother(
            processNoise: config.kalmanProcessNoise,
            measurementNoise: config.kalmanMeasurementNoise
        ) : nil
        if let s2 = initialSecondStar {
            secondKalman?.initialize(at: s2)
        }

        var currentPolaris = initialPolaris
        var currentSecondStar = initialSecondStar
        var prevPolaris: CGPoint?
        var prevSecondStar: CGPoint?

        var transforms: [FrameTransform] = []
        transforms.reserveCapacity(frameCount)

        var totalConfidence = 0.0
        var imgWidth = 0
        var imgHeight = 0

        for i in 0..<frameCount {
            try Task.checkCancellation()
            let img = try await loadLuma(i)
            imgWidth = img.width
            imgHeight = img.height

            let t = (times.indices.contains(i) && times[i] >= 0) ? times[i] : Double(i)

            // Predict position via Kalman filter
            let searchPolaris: CGPoint
            if useKalman && i > 0, let pk = polarisKalman {
                searchPolaris = pk.predict()
            } else {
                searchPolaris = currentPolaris
            }

            let polResult = detector.trackStarInROI(
                image: img,
                center: searchPolaris,
                previousPosition: prevPolaris
            )

            var frameTransform = FrameTransform()
            frameTransform.frameIndex = i
            frameTransform.time = t

            if let trackedP = polResult.point {
                totalConfidence += polResult.confidence
                polarisKalman?.update(with: trackedP)
                let finalPolaris = (useKalman && polarisKalman != nil) ? (polarisKalman?.currentPosition() ?? trackedP) : trackedP
                prevPolaris = currentPolaris
                currentPolaris = finalPolaris

                var currentAngle = 0.0
                if useRotation, let s2 = currentSecondStar {
                    let searchSecond: CGPoint
                    if useKalman && i > 0, let sk = secondKalman {
                        searchSecond = sk.predict()
                    } else {
                        searchSecond = s2
                    }

                    let secResult = detector.trackStarInROI(
                        image: img,
                        center: searchSecond,
                        previousPosition: prevSecondStar
                    )

                    if let trackedS2 = secResult.point {
                        secondKalman?.update(with: trackedS2)
                        let finalS2 = (useKalman && secondKalman != nil) ? (secondKalman?.currentPosition() ?? trackedS2) : trackedS2
                        prevSecondStar = currentSecondStar
                        currentSecondStar = finalS2

                        // Calculate rotation relative to initial line
                        let dInitX = Double(initialSecondStar!.x - initialPolaris.x)
                        let dInitY = Double(initialSecondStar!.y - initialPolaris.y)
                        let initAngle = atan2(dInitY, dInitX)

                        let dCurrX = Double(finalS2.x - finalPolaris.x)
                        let dCurrY = Double(finalS2.y - finalPolaris.y)
                        let currAngle = atan2(dCurrY, dCurrX)

                        currentAngle = currAngle - initAngle
                    }
                }

                // Reference coordinates are from frame 0
                let dx = Double(initialPolaris.x - currentPolaris.x)
                let dy = Double(initialPolaris.y - currentPolaris.y)

                if abs(currentAngle) > 1e-6 {
                    let cosA = cos(currentAngle)
                    let sinA = sin(currentAngle)
                    frameTransform.a = cosA
                    frameTransform.b = -sinA
                    frameTransform.tx = Double(initialPolaris.x) - (cosA * Double(currentPolaris.x) - sinA * Double(currentPolaris.y))
                    frameTransform.c = sinA
                    frameTransform.d = cosA
                    frameTransform.ty = Double(initialPolaris.y) - (sinA * Double(currentPolaris.x) + cosA * Double(currentPolaris.y))
                } else {
                    frameTransform.a = 1.0
                    frameTransform.b = 0.0
                    frameTransform.tx = dx
                    frameTransform.c = 0.0
                    frameTransform.d = 1.0
                    frameTransform.ty = dy
                }
                frameTransform.skipped = false

                progress(i + 1, frameCount, dx, dy)
            } else {
                frameTransform.skipped = true
                progress(i + 1, frameCount, 0.0, 0.0)
            }

            transforms.append(frameTransform)
        }

        let crop = try CropCalculator.calculateCrop(transforms: transforms, width: imgWidth, height: imgHeight)
        let validCount = transforms.filter { !$0.skipped }.count
        let avgConf = validCount > 0 ? totalConfidence / Double(validCount) : 0.0
        let refStars = [initialPolaris] + (initialSecondStar != nil ? [initialSecondStar!] : [])

        return (transforms, crop, refStars, avgConf)
    }
}
