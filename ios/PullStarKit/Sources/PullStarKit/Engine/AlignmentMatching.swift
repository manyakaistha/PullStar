import Foundation
import CoreGraphics

/// Result of matching two star fields.
public struct StarMatch: Sendable {
    /// 3x3 homogeneous transformation matrix mapping source coords -> target coords:
    /// [a, b, tx,
    ///  c, d, ty,
    ///  0, 0,  1]
    public var matrix: [Double]
    public var sourceInliers: [CGPoint]
    public var targetInliers: [CGPoint]
    public var confidence: Double
    public var rmsError: Double

    public var rotationAngleDegrees: Double {
        atan2(matrix[3], matrix[0]) * 180.0 / .pi
    }

    public var translation: CGPoint {
        CGPoint(x: matrix[2], y: matrix[5])
    }

    public init(
        matrix: [Double],
        sourceInliers: [CGPoint],
        targetInliers: [CGPoint],
        confidence: Double,
        rmsError: Double
    ) {
        self.matrix = matrix
        self.sourceInliers = sourceInliers
        self.targetInliers = targetInliers
        self.confidence = confidence
        self.rmsError = rmsError
    }
}

/// Matches star fields between two exposures using invariant triangle (asterism) patterns
/// and RANSAC with 2D rigid least-squares refinement.
///
/// Ported faithfully from `modules/astronomy.py` (`match_sources`, `_validate_correspondences`).
public enum StarFieldMatcher {
    public static let minMatches = 6
    public static let maxStars = 100

    /// Match star points between `source` and `target`.
    public static func match(
        source: [CGPoint],
        target: [CGPoint],
        initialTranslation: CGPoint? = nil
    ) -> StarMatch? {
        guard source.count >= minMatches, target.count >= minMatches else {
            return nil
        }

        // 1. If initial translation is available, try direct nearest-neighbour consensus
        if let initT = initialTranslation {
            if let directMatch = matchWithTranslation(source: source, target: target, translation: initT) {
                return directMatch
            }
        }

        // 2. Multi-tier candidate budget matching (100, 60, 40) to handle faint noise tails
        let largestPool = max(source.count, target.count)
        let budgets = [min(largestPool, maxStars), min(largestPool, 60), min(largestPool, 40)]
        var testedBudgets = Set<Int>()

        for budget in budgets {
            guard testedBudgets.insert(budget).inserted else { continue }
            let srcSubset = Array(source.prefix(budget))
            let dstSubset = Array(target.prefix(budget))

            if let match = matchPool(sourceAll: source, targetAll: target, srcSubset: srcSubset, dstSubset: dstSubset) {
                return match
            }
        }

        return nil
    }

    private static func matchWithTranslation(
        source: [CGPoint],
        target: [CGPoint],
        translation: CGPoint
    ) -> StarMatch? {
        var candidatePairs: [(sIdx: Int, dIdx: Int, d2: Double)] = []

        for (sIdx, src) in source.enumerated() {
            let shiftedX = Double(src.x + translation.x)
            let shiftedY = Double(src.y + translation.y)

            for (dIdx, dst) in target.enumerated() {
                let dx = shiftedX - Double(dst.x)
                let dy = shiftedY - Double(dst.y)
                let d2 = dx * dx + dy * dy
                if d2 < (4.0 * 4.0) {
                    candidatePairs.append((sIdx: sIdx, dIdx: dIdx, d2: d2))
                }
            }
        }

        candidatePairs.sort { $0.d2 < $1.d2 }

        var usedS = Set<Int>()
        var usedD = Set<Int>()
        var srcPts: [CGPoint] = []
        var dstPts: [CGPoint] = []

        for pair in candidatePairs {
            if !usedS.contains(pair.sIdx) && !usedD.contains(pair.dIdx) {
                usedS.insert(pair.sIdx)
                usedD.insert(pair.dIdx)
                srcPts.append(source[pair.sIdx])
                dstPts.append(target[pair.dIdx])
            }
        }

        guard srcPts.count >= minMatches else { return nil }

        return validateCorrespondences(
            fullSource: source,
            fullTarget: target,
            src: srcPts,
            dst: dstPts
        )
    }

    private struct Triangle {
        var r1: Double
        var r2: Double
        var a: Int // vertex between L1 and L2 (opposite longest side L3)
        var b: Int // vertex between L2 and L3 (opposite shortest side L1)
        var c: Int // vertex between L3 and L1 (opposite middle side L2)
    }

    private static func matchPool(
        sourceAll: [CGPoint],
        targetAll: [CGPoint],
        srcSubset: [CGPoint],
        dstSubset: [CGPoint]
    ) -> StarMatch? {
        guard srcSubset.count >= 3, dstSubset.count >= 3 else { return nil }

        // Build triangles for source and target
        let srcTriangles = buildTriangles(points: srcSubset)
        let dstTriangles = buildTriangles(points: dstSubset)

        guard !srcTriangles.isEmpty, !dstTriangles.isEmpty else { return nil }

        // Sort triangles by r1
        let sortedDst = dstTriangles.sorted { $0.r1 < $1.r1 }

        var bestInliers: (src: [CGPoint], dst: [CGPoint])?
        var bestScore = 0.0

        // Find matching triangle pairs (tolerance for side ratios)
        let tolerance = 0.04

        for sTri in srcTriangles {
            // Binary search in sortedDst for range [sTri.r1 - tolerance, sTri.r1 + tolerance]
            let lowR1 = sTri.r1 - tolerance
            let highR1 = sTri.r1 + tolerance

            var low = 0
            var high = sortedDst.count
            while low < high {
                let mid = (low + high) / 2
                if sortedDst[mid].r1 < lowR1 { low = mid + 1 } else { high = mid }
            }

            var idx = low
            while idx < sortedDst.count && sortedDst[idx].r1 <= highR1 {
                let dTri = sortedDst[idx]
                idx += 1

                if abs(sTri.r2 - dTri.r2) > tolerance {
                    continue
                }

                // Hypothesize similarity transform from canonically ordered triangle vertices
                let sA = srcSubset[sTri.a], sB = srcSubset[sTri.b], sC = srcSubset[sTri.c]
                let dA = dstSubset[dTri.a], dB = dstSubset[dTri.b], dC = dstSubset[dTri.c]

                guard let (scale, theta, tx, ty) = fitTriangleSimilarity(s1: sA, s2: sB, s3: sC, d1: dA, d2: dB, d3: dC) else {
                    continue
                }

                // Sky scale should be within [0.98, 1.02] matching astroalign
                guard scale >= 0.98 && scale <= 1.02 else {
                    continue
                }

                // Count inliers across full subset (tolerance = 2.0 px matching astroalign PIXEL_TOL)
                let cosT = cos(theta) * scale
                let sinT = sin(theta) * scale

                // Find all candidate pairs within tolerance
                var candidatePairs: [(sIdx: Int, dIdx: Int, d2: Double)] = []
                for (sIdx, srcP) in srcSubset.enumerated() {
                    let predX = cosT * Double(srcP.x) - sinT * Double(srcP.y) + tx
                    let predY = sinT * Double(srcP.x) + cosT * Double(srcP.y) + ty

                    for (dIdx, dstP) in dstSubset.enumerated() {
                        let dx = predX - Double(dstP.x)
                        let dy = predY - Double(dstP.y)
                        let d2 = dx * dx + dy * dy
                        if d2 <= (2.0 * 2.0) {
                            candidatePairs.append((sIdx: sIdx, dIdx: dIdx, d2: d2))
                        }
                    }
                }

                // Sort pairs by distance so closest points pair first (avoids greedy stealing)
                candidatePairs.sort { $0.d2 < $1.d2 }

                var inlierSrc: [CGPoint] = []
                var inlierDst: [CGPoint] = []
                var usedS = Set<Int>()
                var usedD = Set<Int>()

                for pair in candidatePairs {
                    if !usedS.contains(pair.sIdx) && !usedD.contains(pair.dIdx) {
                        usedS.insert(pair.sIdx)
                        usedD.insert(pair.dIdx)
                        inlierSrc.append(srcSubset[pair.sIdx])
                        inlierDst.append(dstSubset[pair.dIdx])
                    }
                }

                let count = inlierSrc.count
                guard count >= minMatches else { continue }

                var sumD2 = 0.0
                for (sP, dP) in zip(inlierSrc, inlierDst) {
                    let px = cosT * Double(sP.x) - sinT * Double(sP.y) + tx
                    let py = sinT * Double(sP.x) + cosT * Double(sP.y) + ty
                    let ex = px - Double(dP.x)
                    let ey = py - Double(dP.y)
                    sumD2 += ex * ex + ey * ey
                }
                let candRms = sqrt(sumD2 / Double(count))
                let candScore = Double(count) / (1.0 + candRms)

                if candScore > bestScore {
                    bestScore = candScore
                    bestInliers = (inlierSrc, inlierDst)

                    // Early exit if strong consensus found
                    if count >= Int(Double(srcSubset.count) * 0.8) && candRms < 0.5 {
                        break
                    }
                }
            }

            if let inliers = bestInliers, inliers.src.count >= Int(Double(srcSubset.count) * 0.8) {
                break
            }
        }

        guard let inliers = bestInliers, inliers.src.count >= minMatches else {
            return nil
        }

        return validateCorrespondences(
            fullSource: sourceAll,
            fullTarget: targetAll,
            src: inliers.src,
            dst: inliers.dst
        )
    }

    private static func buildTriangles(points: [CGPoint]) -> [Triangle] {
        let n = points.count
        guard n >= 3 else { return [] }

        var triangles: [Triangle] = []
        triangles.reserveCapacity(min(4000, n * 40))

        var seen = Set<Int>()

        // For each point, find up to 8 nearest neighbors
        for i in 0..<n {
            let pI = points[i]
            var neighbors: [(idx: Int, dist: Double)] = []
            for j in 0..<n where i != j {
                let dx = Double(pI.x - points[j].x)
                let dy = Double(pI.y - points[j].y)
                neighbors.append((j, sqrt(dx * dx + dy * dy)))
            }
            neighbors.sort { $0.dist < $1.dist }
            let kNearest = neighbors.prefix(8)

            for a in 0..<kNearest.count {
                for b in (a + 1)..<kNearest.count {
                    let idx1 = i
                    let idx2 = kNearest[a].idx
                    let idx3 = kNearest[b].idx

                    // Canonical unique unordered triplet key
                    let sortedIdx = [idx1, idx2, idx3].sorted()
                    let key = sortedIdx[0] | (sortedIdx[1] << 10) | (sortedIdx[2] << 20)
                    guard seen.insert(key).inserted else { continue }

                    let p1 = points[idx1]
                    let p2 = points[idx2]
                    let p3 = points[idx3]

                    let d12 = hypot(Double(p1.x - p2.x), Double(p1.y - p2.y))
                    let d23 = hypot(Double(p2.x - p3.x), Double(p2.y - p3.y))
                    let d31 = hypot(Double(p3.x - p1.x), Double(p3.y - p1.y))

                    // Sides with their opposite vertex
                    var sides: [(len: Double, opp: Int)] = [
                        (d12, idx3),
                        (d23, idx1),
                        (d31, idx2)
                    ]
                    sides.sort { $0.len < $1.len }

                    let l1 = sides[0].len
                    let l2 = sides[1].len
                    let l3 = sides[2].len

                    // Reject degenerate or collinear triangles
                    guard l1 >= 3.0, l3 <= 3000.0 else { continue }
                    let s = (l1 + l2 + l3) * 0.5
                    let area2 = s * (s - l1) * (s - l2) * (s - l3)
                    guard area2 >= 1.0 else { continue }

                    // Vertex opposite to L3 is between L1 and L2
                    let vA = sides[2].opp
                    // Vertex opposite to L1 is between L2 and L3
                    let vB = sides[0].opp
                    // Vertex opposite to L2 is between L3 and L1
                    let vC = sides[1].opp

                    triangles.append(Triangle(
                        r1: l1 / l3,
                        r2: l2 / l3,
                        a: vA,
                        b: vB,
                        c: vC
                    ))
                }
            }
        }

        return triangles
    }

    /// Fit similarity transform (scale, theta, tx, ty) from 3 point pairs
    private static func fitTriangleSimilarity(
        s1: CGPoint, s2: CGPoint, s3: CGPoint,
        d1: CGPoint, d2: CGPoint, d3: CGPoint
    ) -> (scale: Double, theta: Double, tx: Double, ty: Double)? {
        let srcMeanX = (Double(s1.x) + Double(s2.x) + Double(s3.x)) / 3.0
        let srcMeanY = (Double(s1.y) + Double(s2.y) + Double(s3.y)) / 3.0
        let dstMeanX = (Double(d1.x) + Double(d2.x) + Double(d3.x)) / 3.0
        let dstMeanY = (Double(d1.y) + Double(d2.y) + Double(d3.y)) / 3.0

        let sPoints = [(Double(s1.x) - srcMeanX, Double(s1.y) - srcMeanY),
                       (Double(s2.x) - srcMeanX, Double(s2.y) - srcMeanY),
                       (Double(s3.x) - srcMeanX, Double(s3.y) - srcMeanY)]

        let dPoints = [(Double(d1.x) - dstMeanX, Double(d1.y) - dstMeanY),
                       (Double(d2.x) - dstMeanX, Double(d2.y) - dstMeanY),
                       (Double(d3.x) - dstMeanX, Double(d3.y) - dstMeanY)]

        var sNorm = 0.0
        var sxx = 0.0, sxy = 0.0, syx = 0.0, syy = 0.0

        for idx in 0..<3 {
            let (sx, sy) = sPoints[idx]
            let (dx, dy) = dPoints[idx]
            sNorm += sx * sx + sy * sy
            sxx += sx * dx
            sxy += sx * dy
            syx += sy * dx
            syy += sy * dy
        }

        guard sNorm > 1e-6 else { return nil }

        let a = (sxx + syy) / sNorm
        let b = (sxy - syx) / sNorm
        let scale = sqrt(a * a + b * b)
        let theta = atan2(b, a)

        let tx = dstMeanX - (a * srcMeanX - b * srcMeanY)
        let ty = dstMeanY - (b * srcMeanX + a * srcMeanY)

        return (scale, theta, tx, ty)
    }

    /// Unit-scale 2D rigid refinement and correspondence validation
    public static func validateCorrespondences(
        fullSource: [CGPoint],
        fullTarget: [CGPoint],
        src: [CGPoint],
        dst: [CGPoint]
    ) -> StarMatch? {
        guard src.count >= minMatches, src.count == dst.count else { return nil }

        var curSrc = src
        var curDst = dst

        var bestMatrix: [Double] = [
            1, 0, 0,
            0, 1, 0,
            0, 0, 1
        ]
        var lastErrors: [Double] = []

        // Two iterations of outlier filtering and rigid fit
        for _ in 0..<2 {
            let m = curSrc.count
            guard m >= minMatches else { return nil }

            var meanSrcX = 0.0, meanSrcY = 0.0
            var meanDstX = 0.0, meanDstY = 0.0
            for i in 0..<m {
                meanSrcX += Double(curSrc[i].x)
                meanSrcY += Double(curSrc[i].y)
                meanDstX += Double(curDst[i].x)
                meanDstY += Double(curDst[i].y)
            }
            meanSrcX /= Double(m)
            meanSrcY /= Double(m)
            meanDstX /= Double(m)
            meanDstY /= Double(m)

            var sxx = 0.0, sxy = 0.0, syx = 0.0, syy = 0.0
            for i in 0..<m {
                let dsx = Double(curSrc[i].x) - meanSrcX
                let dsy = Double(curSrc[i].y) - meanSrcY
                let ddx = Double(curDst[i].x) - meanDstX
                let ddy = Double(curDst[i].y) - meanDstY
                sxx += dsx * ddx
                sxy += dsx * ddy
                syx += dsy * ddx
                syy += dsy * ddy
            }

            // Closed-form 2D optimal rotation angle matching SVD
            let theta = atan2(sxy - syx, sxx + syy)
            let cosT = cos(theta)
            let sinT = sin(theta)

            let tx = meanDstX - (cosT * meanSrcX - sinT * meanSrcY)
            let ty = meanDstY - (sinT * meanSrcX + cosT * meanSrcY)

            bestMatrix = [
                cosT, -sinT, tx,
                sinT,  cosT, ty,
                   0,     0,  1
            ]

            var nextSrc: [CGPoint] = []
            var nextDst: [CGPoint] = []
            var errors: [Double] = []

            for i in 0..<m {
                let px = Double(curSrc[i].x)
                let py = Double(curSrc[i].y)
                let predX = cosT * px - sinT * py + tx
                let predY = sinT * px + cosT * py + ty
                let err = hypot(predX - Double(curDst[i].x), predY - Double(curDst[i].y))
                if err <= 2.0 {
                    nextSrc.append(curSrc[i])
                    nextDst.append(curDst[i])
                    errors.append(err)
                }
            }

            guard nextSrc.count >= minMatches else { return nil }
            curSrc = nextSrc
            curDst = nextDst
            lastErrors = errors
        }

        let m = curSrc.count
        guard m >= minMatches else { return nil }

        let rms = sqrt(lastErrors.reduce(0.0) { $0 + $1 * $1 } / Double(m))
        let minPool = min(fullSource.count, fullTarget.count)
        let fraction = Double(m) / Double(minPool)
        let required = max(minMatches, min(20, Int(ceil(0.3 * Double(minPool)))))

        var minX = Double.greatestFiniteMagnitude, maxX = -Double.greatestFiniteMagnitude
        var minY = Double.greatestFiniteMagnitude, maxY = -Double.greatestFiniteMagnitude
        for pt in curSrc {
            let x = Double(pt.x)
            let y = Double(pt.y)
            minX = min(minX, x)
            maxX = max(maxX, x)
            minY = min(minY, y)
            maxY = max(maxY, y)
        }
        let spread = hypot(maxX - minX, maxY - minY)

        guard m >= required, rms <= 1.5, spread >= 20.0 else {
            return nil
        }

        let confidence = min(1.0, fraction) / (1.0 + rms)

        return StarMatch(
            matrix: bestMatrix,
            sourceInliers: curSrc,
            targetInliers: curDst,
            confidence: confidence,
            rmsError: rms
        )
    }
}
