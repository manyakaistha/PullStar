import Foundation
import CoreGraphics
import Accelerate

/// A detected star with sub-pixel centroid coordinates, flux, SNR, and FWHM.
public struct DetectedStar: Sendable, Equatable {
    public var point: CGPoint
    public var flux: Float
    public var snr: Float
    public var fwhm: Float

    public init(point: CGPoint, flux: Float, snr: Float = 0, fwhm: Float = 0) {
        self.point = point
        self.flux = flux
        self.snr = snr
        self.fwhm = fwhm
    }
}

/// Star detector implementing background estimation + subtraction (via Accelerate/vDSP),
/// local-peak detection, hot-pixel / cosmic-ray rejection, sub-pixel centroiding,
/// multiscale flux/FWHM filtering, and spatial dispersion quotas.
///
/// Supports standard star fields as well as 'noisy RAW recovery' mode (recovering faint
/// and streaked stars from low-signal high-noise phone/camera exposures).
public final class StarDetector: Sendable {
    public static let maxDetectionDimension: Int = 2048

    public init() {}

    /// Detect stars in the given image.
    /// Returns sorted star list (by flux and SNR descending).
    public func detectStars(
        in image: PixelImage,
        maxStars: Int = 100,
        noisyRawRecovery: Bool = false
    ) -> [DetectedStar] {
        guard image.width >= 12, image.height >= 12, !image.data.isEmpty else {
            return []
        }

        // 1. Extract grayscale luma buffer
        let origW = image.width
        let origH = image.height
        var luma = [Float](repeating: 0, count: origW * origH)

        if image.channels == 1 {
            luma = image.data
        } else if image.channels >= 3 {
            let ch = image.channels
            image.data.withUnsafeBufferPointer { ptr in
                guard let base = ptr.baseAddress else { return }
                for i in 0..<(origW * origH) {
                    let r = base[i * ch + 0]
                    let g = base[i * ch + 1]
                    let b = base[i * ch + 2]
                    luma[i] = 0.299 * r + 0.587 * g + 0.114 * b
                }
            }
        }

        // 2. Downscale to bounded analysis copy if largest dimension exceeds 2048
        let maxDim = max(origW, origH)
        let scale = min(1.0, Double(Self.maxDetectionDimension) / Double(maxDim))
        let targetW: Int
        let targetH: Int
        var working: [Float]

        if scale < 1.0 {
            targetW = max(12, Int(round(Double(origW) * scale)))
            targetH = max(12, Int(round(Double(origH) * scale)))
            working = [Float](repeating: 0, count: targetW * targetH)

            // Resample with bilinear / area interpolation
            let stepX = Double(origW) / Double(targetW)
            let stepY = Double(origH) / Double(targetH)

            for ty in 0..<targetH {
                let sy = Double(ty) * stepY
                let y0 = Int(sy)
                let y1 = min(origH - 1, y0 + 1)
                let fy = Float(sy - Double(y0))

                for tx in 0..<targetW {
                    let sx = Double(tx) * stepX
                    let x0 = Int(sx)
                    let x1 = min(origW - 1, x0 + 1)
                    let fx = Float(sx - Double(x0))

                    let v00 = luma[y0 * origW + x0]
                    let v01 = luma[y0 * origW + x1]
                    let v10 = luma[y1 * origW + x0]
                    let v11 = luma[y1 * origW + x1]

                    let top = v00 * (1.0 - fx) + v01 * fx
                    let bot = v10 * (1.0 - fx) + v11 * fx
                    working[ty * targetW + tx] = top * (1.0 - fy) + bot * fy
                }
            }
        } else {
            targetW = origW
            targetH = origH
            working = luma
        }

        let scaleX = Double(origW) / Double(targetW)
        let scaleY = Double(origH) / Double(targetH)

        // 3. Contrast & percentile linear stretch
        let count = targetW * targetH
        let strideStep = max(1, Int(sqrt(Double(count) / 160_000.0)))
        var subsample: [Float] = []
        subsample.reserveCapacity(count / (strideStep * strideStep) + 10)
        for y in stride(from: 0, to: targetH, by: strideStep) {
            for x in stride(from: 0, to: targetW, by: strideStep) {
                let v = working[y * targetW + x]
                if v.isFinite { subsample.append(v) }
            }
        }

        guard !subsample.isEmpty else { return [] }
        subsample.sort()

        let blackIdx = max(0, min(subsample.count - 1, Int(Double(subsample.count) * 0.005)))
        let whiteIdx = max(0, min(subsample.count - 1, Int(Double(subsample.count) * 0.995)))
        let black = subsample[blackIdx]
        let white = subsample[whiteIdx]
        let range = max(white - black, 1e-6)

        // working = (working - black) / range via vDSP
        var negBlack = -black
        var invRange = 1.0 / range
        vDSP_vsadd(working, 1, &negBlack, &working, 1, vDSP_Length(count))
        vDSP_vsmul(working, 1, &invRange, &working, 1, vDSP_Length(count))

        // 4. Background estimation & subtraction (grid-based median & noise map)
        let boxSize = max(16, min(64, min(targetW, targetH) / 4))
        let gridCols = (targetW + boxSize - 1) / boxSize
        let gridRows = (targetH + boxSize - 1) / boxSize

        var bkgGrid = [Float](repeating: 0, count: gridCols * gridRows)
        var rmsGrid = [Float](repeating: 0, count: gridCols * gridRows)

        for gy in 0..<gridRows {
            let y0 = gy * boxSize
            let y1 = min(targetH, y0 + boxSize)
            for gx in 0..<gridCols {
                let x0 = gx * boxSize
                let x1 = min(targetW, x0 + boxSize)

                var blockVals: [Float] = []
                blockVals.reserveCapacity((y1 - y0) * (x1 - x0))
                for y in y0..<y1 {
                    for x in x0..<x1 {
                        blockVals.append(working[y * targetW + x])
                    }
                }
                blockVals.sort()
                let med = blockVals[blockVals.count / 2]
                bkgGrid[gy * gridCols + gx] = med

                // MAD for noise estimation: median(|x - med|) * 1.4826
                var diffs = blockVals.map { abs($0 - med) }
                diffs.sort()
                let mad = diffs[diffs.count / 2] * 1.4826
                rmsGrid[gy * gridCols + gx] = max(1e-6, mad)
            }
        }

        // Smooth background grids with 3x3 filter
        let smoothBkg = smoothGrid(bkgGrid, cols: gridCols, rows: gridRows)
        let smoothRms = smoothGrid(rmsGrid, cols: gridCols, rows: gridRows)

        // Interpolate background and rms to full working resolution and whiten noise:
        // normalized = (working - bkg) / max(rms, noiseFloor)
        var sortedRms = smoothRms.sorted()
        let p10Rms = sortedRms[max(0, Int(Double(sortedRms.count) * 0.1))]
        let noiseFloor = max(p10Rms * 0.3, 1e-6)

        var normalized = [Float](repeating: 0, count: count)
        for y in 0..<targetH {
            let gy = (Double(y) / Double(boxSize)).clamped(to: 0...Double(gridRows - 1))
            let gy0 = Int(gy)
            let gy1 = min(gridRows - 1, gy0 + 1)
            let ty = Float(gy - Double(gy0))

            for x in 0..<targetW {
                let gx = (Double(x) / Double(boxSize)).clamped(to: 0...Double(gridCols - 1))
                let gx0 = Int(gx)
                let gx1 = min(gridCols - 1, gx0 + 1)
                let tx = Float(gx - Double(gx0))

                let b00 = smoothBkg[gy0 * gridCols + gx0]
                let b01 = smoothBkg[gy0 * gridCols + gx1]
                let b10 = smoothBkg[gy1 * gridCols + gx0]
                let b11 = smoothBkg[gy1 * gridCols + gx1]
                let bkgVal = (b00 * (1 - tx) + b01 * tx) * (1 - ty) + (b10 * (1 - tx) + b11 * tx) * ty

                let r00 = smoothRms[gy0 * gridCols + gx0]
                let r01 = smoothRms[gy0 * gridCols + gx1]
                let r10 = smoothRms[gy1 * gridCols + gx0]
                let r11 = smoothRms[gy1 * gridCols + gx1]
                let rmsVal = max(noiseFloor, (r00 * (1 - tx) + r01 * tx) * (1 - ty) + (r10 * (1 - tx) + r11 * tx) * ty)

                normalized[y * targetW + x] = (working[y * targetW + x] - bkgVal) / rmsVal
            }
        }

        // Mild 3x3 Gaussian smoothing on normalized
        let smoothed = gaussianBlur3x3(normalized, width: targetW, height: targetH)

        // 5. Local Peak Detection & Star Candidate Extraction
        let snrThreshold: Float = noisyRawRecovery ? 2.4 : 2.8
        let maxCoreRatio: Float = noisyRawRecovery ? 0.75 : 0.65
        let margin = 5

        struct Candidate {
            var x: Double
            var y: Double
            var flux: Float
            var snr: Float
            var fwhm: Float
        }

        var candidates: [Candidate] = []

        for y in margin..<(targetH - margin) {
            let rowOffset = y * targetW
            for x in margin..<(targetW - margin) {
                let val = smoothed[rowOffset + x]
                guard val >= snrThreshold else { continue }

                // Check 8-connected local maximum
                if val <= smoothed[rowOffset - targetW + x - 1] ||
                   val <= smoothed[rowOffset - targetW + x] ||
                   val <= smoothed[rowOffset - targetW + x + 1] ||
                   val <= smoothed[rowOffset + x - 1] ||
                   val <  smoothed[rowOffset + x + 1] ||
                   val <  smoothed[rowOffset + targetW + x - 1] ||
                   val <  smoothed[rowOffset + targetW + x] ||
                   val <  smoothed[rowOffset + targetW + x + 1] {
                    continue
                }

                // Evaluate 7x7 patch around peak
                var rimVals: [Float] = []
                rimVals.reserveCapacity(24)
                for dy in -3...3 {
                    for dx in -3...3 {
                        if abs(dx) == 3 || abs(dy) == 3 {
                            rimVals.append(normalized[(y + dy) * targetW + (x + dx)])
                        }
                    }
                }
                rimVals.sort()
                let rimMed = rimVals[rimVals.count / 2]

                var coreSum: Float = 0
                var totalPositive: Float = 0
                var peakPositive: Float = 0

                var sumW: Float = 0
                var sumWX: Float = 0
                var sumWY: Float = 0
                var sumWR2: Float = 0

                for dy in -3...3 {
                    for dx in -3...3 {
                        let rawSig = normalized[(y + dy) * targetW + (x + dx)] - rimMed
                        let sig = max(0, rawSig)
                        totalPositive += sig
                        if abs(dx) <= 1 && abs(dy) <= 1 {
                            coreSum += sig
                        }
                        if dx == 0 && dy == 0 {
                            peakPositive = sig
                        }

                        // Centroid weighting
                        let w = sig
                        sumW += w
                        sumWX += w * Float(dx)
                        sumWY += w * Float(dy)
                        sumWR2 += w * Float(dx * dx + dy * dy)
                    }
                }

                guard sumW > 1e-4 else { continue }

                // Shape check 1: Hot pixel rejection (single pixel doesn't hold overwhelming core flux)
                if peakPositive > maxCoreRatio * max(coreSum, 1e-6) {
                    continue
                }

                // Shape check 2: Core concentration (not an extended diffuse cloud/roof)
                if coreSum < 0.20 * totalPositive {
                    continue
                }

                // Sub-pixel centroid
                let subX = Double(x) + Double(sumWX / sumW)
                let subY = Double(y) + Double(sumWY / sumW)

                // Clamp drift from integer peak
                if abs(subX - Double(x)) > 1.8 || abs(subY - Double(y)) > 1.8 {
                    continue
                }

                // FWHM estimation
                let sigma2 = max(0.1, (sumWR2 / sumW) * 0.5)
                let fwhm = 2.355 * sqrt(sigma2)
                let maxFwhm: Float = noisyRawRecovery ? 12.0 : 8.5
                guard fwhm >= 0.8 && fwhm <= maxFwhm else { continue }

                candidates.append(Candidate(
                    x: subX,
                    y: subY,
                    flux: totalPositive,
                    snr: val,
                    fwhm: fwhm
                ))
            }
        }

        // 6. Spatial dispersion & quota distribution
        candidates.sort { ($0.flux * 0.5 + $0.snr * 2.0) > ($1.flux * 0.5 + $1.snr * 2.0) }

        let gridWCount = 8
        let gridHCount = 6
        var cellCounts = [Int](repeating: 0, count: gridWCount * gridHCount)
        let quota = max(4, Int(ceil(Double(maxStars) / 24.0)))

        var selected: [DetectedStar] = []
        selected.reserveCapacity(min(maxStars, candidates.count))

        for cand in candidates {
            let gx = min(gridWCount - 1, max(0, Int(cand.x * Double(gridWCount) / Double(targetW))))
            let gy = min(gridHCount - 1, max(0, Int(cand.y * Double(gridHCount) / Double(targetH))))
            let cellIdx = gy * gridWCount + gx

            if cellCounts[cellIdx] >= quota {
                continue
            }

            // Minimum separation check (4 pixels in analysis coordinates)
            let tooClose = selected.contains { existing in
                let ex = (existing.point.x + 0.5) / scaleX - 0.5
                let ey = (existing.point.y + 0.5) / scaleY - 0.5
                let dx = cand.x - ex
                let dy = cand.y - ey
                return (dx * dx + dy * dy) < 16.0
            }
            if tooClose { continue }

            cellCounts[cellIdx] += 1

            // Map back to original image coordinates:
            // x_orig = (cand.x + 0.5) * scaleX - 0.5
            let origX = (cand.x + 0.5) * scaleX - 0.5
            let origY = (cand.y + 0.5) * scaleY - 0.5

            selected.append(DetectedStar(
                point: CGPoint(x: origX, y: origY),
                flux: cand.flux,
                snr: cand.snr,
                fwhm: cand.fwhm
            ))

            if selected.count >= maxStars {
                break
            }
        }

        return selected
    }

    /// Convenience to return points directly
    public func detectStarPoints(
        in image: PixelImage,
        maxStars: Int = 100,
        noisyRawRecovery: Bool = false
    ) -> [CGPoint] {
        detectStars(in: image, maxStars: maxStars, noisyRawRecovery: noisyRawRecovery).map(\.point)
    }

    /// Track a star in a local ROI around expected position (for manual Polaris / second star tracking).
    public func trackStarInROI(
        image: PixelImage,
        center: CGPoint,
        previousPosition: CGPoint? = nil,
        searchWindowSize: Int = 100,
        maxJumpThreshold: Double = 50.0,
        thresholdPercentile: Double = 99.0,
        minBlobArea: Int = 3,
        maxBlobArea: Int = 500
    ) -> (point: CGPoint?, confidence: Double, maxBrightness: Float, status: String) {
        let w = image.width
        let h = image.height
        let cx = Int(center.x)
        let cy = Int(center.y)
        let half = searchWindowSize / 2

        let x0 = max(0, cx - half)
        let x1 = min(w, cx + half)
        let y0 = max(0, cy - half)
        let y1 = min(h, cy + half)

        guard x1 > x0, y1 > y0 else {
            return (nil, 0.0, 0, "ROI outside image")
        }

        let roiW = x1 - x0
        let roiH = y1 - y0
        var roi = [Float](repeating: 0, count: roiW * roiH)

        let ch = image.channels
        image.data.withUnsafeBufferPointer { ptr in
            guard let base = ptr.baseAddress else { return }
            for ry in 0..<roiH {
                let imgY = y0 + ry
                for rx in 0..<roiW {
                    let imgX = x0 + rx
                    let idx = imgY * w + imgX
                    if ch == 1 {
                        roi[ry * roiW + rx] = base[idx]
                    } else {
                        let r = base[idx * ch + 0]
                        let g = base[idx * ch + 1]
                        let b = base[idx * ch + 2]
                        roi[ry * roiW + rx] = 0.299 * r + 0.587 * g + 0.114 * b
                    }
                }
            }
        }

        // Gaussian blur 5x5
        let blurred = gaussianBlur3x3(roi, width: roiW, height: roiH)

        // Threshold percentile
        var sortedVals = blurred.sorted()
        let pIdx = max(0, min(sortedVals.count - 1, Int(Double(sortedVals.count) * (thresholdPercentile / 100.0))))
        let thresh = sortedVals[pIdx]

        // Find connected components in binary mask
        var binary = [UInt8](repeating: 0, count: roiW * roiH)
        for i in 0..<binary.count {
            if blurred[i] >= thresh && blurred[i] > 1e-4 {
                binary[i] = 1
            }
        }

        // Connected component labeling (two-pass BFS)
        var labels = [Int](repeating: 0, count: roiW * roiH)
        var labelCount = 0
        struct BlobInfo {
            var label: Int
            var area: Int
            var sumX: Double
            var sumY: Double
            var maxVal: Float
        }
        var blobs: [BlobInfo] = []

        for ry in 0..<roiH {
            for rx in 0..<roiW {
                let idx = ry * roiW + rx
                if binary[idx] == 1 && labels[idx] == 0 {
                    labelCount += 1
                    var area = 0
                    var sx: Double = 0
                    var sy: Double = 0
                    var maxV: Float = 0

                    var queue: [(Int, Int)] = [(rx, ry)]
                    labels[idx] = labelCount

                    var qHead = 0
                    while qHead < queue.count {
                        let (qx, qy) = queue[qHead]
                        qHead += 1

                        area += 1
                        sx += Double(qx)
                        sy += Double(qy)
                        let val = blurred[qy * roiW + qx]
                        if val > maxV { maxV = val }

                        for (dx, dy) in [(-1,0), (1,0), (0,-1), (0,1), (-1,-1), (1,-1), (-1,1), (1,1)] {
                            let nx = qx + dx
                            let ny = qy + dy
                            if nx >= 0 && nx < roiW && ny >= 0 && ny < roiH {
                                let nIdx = ny * roiW + nx
                                if binary[nIdx] == 1 && labels[nIdx] == 0 {
                                    labels[nIdx] = labelCount
                                    queue.append((nx, ny))
                                }
                            }
                        }
                    }

                    if area >= minBlobArea && area <= maxBlobArea {
                        blobs.append(BlobInfo(label: labelCount, area: area, sumX: sx, sumY: sy, maxVal: maxV))
                    }
                }
            }
        }

        guard !blobs.isEmpty else {
            return (nil, 0.0, 0, "No star blob found")
        }

        // Find blob closest to ROI center
        let roiCenterX = Double(roiW) / 2.0
        let roiCenterY = Double(roiH) / 2.0
        var bestBlob: BlobInfo?
        var bestDist = Double.greatestFiniteMagnitude

        for b in blobs {
            let cx = b.sumX / Double(b.area)
            let cy = b.sumY / Double(b.area)
            let dist = sqrt((cx - roiCenterX) * (cx - roiCenterX) + (cy - roiCenterY) * (cy - roiCenterY))
            if dist < bestDist {
                bestDist = dist
                bestBlob = b
            }
        }

        guard let blob = bestBlob else {
            return (nil, 0.0, 0, "No valid blob near center")
        }

        // Sub-pixel centroid using intensity moments
        var moment00: Double = 0
        var moment10: Double = 0
        var moment01: Double = 0

        for ry in 0..<roiH {
            for rx in 0..<roiW {
                let idx = ry * roiW + rx
                if labels[idx] == blob.label {
                    let weight = Double(blurred[idx])
                    moment00 += weight
                    moment10 += weight * Double(rx)
                    moment01 += weight * Double(ry)
                }
            }
        }

        let localX: Double
        let localY: Double
        if moment00 > 1e-6 {
            localX = moment10 / moment00
            localY = moment01 / moment00
        } else {
            localX = blob.sumX / Double(blob.area)
            localY = blob.sumY / Double(blob.area)
        }

        let globalX = localX + Double(x0)
        let globalY = localY + Double(y0)
        let foundPoint = CGPoint(x: globalX, y: globalY)

        // Jump check
        if let prev = previousPosition {
            let jx = globalX - Double(prev.x)
            let jy = globalY - Double(prev.y)
            let jump = sqrt(jx * jx + jy * jy)
            if jump > maxJumpThreshold {
                return (foundPoint, 0.3, blob.maxVal, "Jump too large: \(jump)")
            }
        }

        let areaScore = min(1.0, Double(blob.area) / Double(minBlobArea + maxBlobArea) * 2.0)
        let posScore = max(0.0, 1.0 - bestDist / max(1.0, Double(half)))
        let conf = min(1.0, areaScore * 0.4 + posScore * 0.6)

        return (foundPoint, conf, blob.maxVal, "Success")
    }
}

// MARK: - Internal Image Helpers

private func smoothGrid(_ grid: [Float], cols: Int, rows: Int) -> [Float] {
    var out = grid
    for r in 0..<rows {
        let r0 = max(0, r - 1)
        let r1 = min(rows - 1, r + 1)
        for c in 0..<cols {
            let c0 = max(0, c - 1)
            let c1 = min(cols - 1, c + 1)

            var sum: Float = 0
            var count: Float = 0
            for y in r0...r1 {
                for x in c0...c1 {
                    sum += grid[y * cols + x]
                    count += 1
                }
            }
            out[r * cols + c] = sum / count
        }
    }
    return out
}

private func gaussianBlur3x3(_ input: [Float], width: Int, height: Int) -> [Float] {
    var output = input
    let kernel: [Float] = [
        1/16, 2/16, 1/16,
        2/16, 4/16, 2/16,
        1/16, 2/16, 1/16
    ]

    for y in 1..<(height - 1) {
        let row = y * width
        for x in 1..<(width - 1) {
            var sum: Float = 0
            var ki = 0
            for dy in -1...1 {
                let r = (y + dy) * width
                for dx in -1...1 {
                    sum += input[r + (x + dx)] * kernel[ki]
                    ki += 1
                }
            }
            output[row + x] = sum
        }
    }
    return output
}

private extension Comparable {
    func clamped(to limits: ClosedRange<Self>) -> Self {
        min(max(self, limits.lowerBound), limits.upperBound)
    }
}
