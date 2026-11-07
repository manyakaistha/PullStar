import Foundation
import CoreGraphics

/// Mathematical model representing smooth sky rotation and constant-speed circular or linear trajectory over time.
///
/// Ported from `backend/engine/field_alignment.py`. Retains genuine stellar rotation trails while
/// removing framewise camera wobble/jitter.
public struct FieldAnalysisModel: Sendable {
    public var angleCoefficients: [Double] // [c0, c1] where angle(t) = c0 + c1 * t
    public var translationCoeffsX: [Double] // basis coefficients for X translation
    public var translationCoeffsY: [Double] // basis coefficients for Y translation
    public var timeSpan: Double
    public var curved: Bool

    public init(
        angleCoefficients: [Double],
        translationCoeffsX: [Double],
        translationCoeffsY: [Double],
        timeSpan: Double,
        curved: Bool
    ) {
        self.angleCoefficients = angleCoefficients
        self.translationCoeffsX = translationCoeffsX
        self.translationCoeffsY = translationCoeffsY
        self.timeSpan = max(1.0, timeSpan)
        self.curved = curved
    }

    /// Evaluates the smooth field motion matrix at a given time (in seconds).
    /// Returns 3x3 row-major homogeneous transform.
    public func motionAt(time: Double) -> [Double] {
        let t = time / timeSpan
        let angle = angleCoefficients[0] + angleCoefficients[1] * t
        let basis = Self.translationBasis(t: t, angularSpeed: angleCoefficients[1], curved: curved)

        var tx = 0.0
        var ty = 0.0
        for i in 0..<basis.count {
            tx += basis[i] * translationCoeffsX[i]
            ty += basis[i] * translationCoeffsY[i]
        }

        let cosA = cos(angle)
        let sinA = sin(angle)

        return [
            cosA, -sinA, tx,
            sinA,  cosA, ty,
               0,     0,  1
        ]
    }

    /// Basis functions for translation trajectory.
    ///
    /// Normalized circular basis remains well-conditioned for small arcs:
    /// [1, sin(w*t)/w, (1 - cos(w*t))/w^2]
    public static func translationBasis(t: Double, angularSpeed: Double, curved: Bool) -> [Double] {
        if !curved {
            return [1.0, t]
        }
        let w = angularSpeed
        let w2 = w * w
        let term1 = abs(w) > 1e-7 ? sin(w * t) / w : t
        let term2 = abs(w2) > 1e-12 ? (1.0 - cos(w * t)) / w2 : 0.5 * t * t
        return [1.0, term1, term2]
    }

    /// Multiplies two 3x3 matrices in row-major order: A @ B
    public static func multiply3x3(_ a: [Double], _ b: [Double]) -> [Double] {
        var res = [Double](repeating: 0, count: 9)
        for r in 0..<3 {
            for c in 0..<3 {
                res[r * 3 + c] = a[r * 3 + 0] * b[0 * 3 + c] +
                                 a[r * 3 + 1] * b[1 * 3 + c] +
                                 a[r * 3 + 2] * b[2 * 3 + c]
            }
        }
        return res
    }

    /// Inverts a 3x3 homogeneous affine matrix:
    /// [a, b, tx,
    ///  c, d, ty,
    ///  0, 0,  1]
    public static func invert3x3Affine(_ m: [Double]) -> [Double]? {
        let a = m[0], b = m[1], tx = m[2]
        let c = m[3], d = m[4], ty = m[5]

        let det = a * d - b * c
        guard abs(det) > 1e-12 else { return nil }

        let invDet = 1.0 / det
        let invA =  d * invDet
        let invB = -b * invDet
        let invC = -c * invDet
        let invD =  a * invDet

        let invTx = -(invA * tx + invB * ty)
        let invTy = -(invC * tx + invD * ty)

        return [
            invA, invB, invTx,
            invC, invD, invTy,
               0,    0,     1
        ]
    }

    /// Unwraps angles across an array to eliminate 2*pi phase jumps.
    public static func unwrapAngles(_ angles: [Double]) -> [Double] {
        guard !angles.isEmpty else { return [] }
        var unwrapped = angles
        for i in 1..<unwrapped.count {
            var diff = unwrapped[i] - unwrapped[i - 1]
            while diff > .pi { diff -= 2 * .pi }
            while diff < -.pi { diff += 2 * .pi }
            unwrapped[i] = unwrapped[i - 1] + diff
        }
        return unwrapped
    }

    /// Robust IRLS (Iteratively Reweighted Least Squares) fit with soft-L1 loss.
    ///
    /// Mirrors scipy.optimize.least_squares(loss="soft_l1", f_scale=noise).
    public static func robustFit(design: [[Double]], values: [Double], noise: Double) -> [Double] {
        let n = design.count
        guard n > 0 else { return [] }
        let p = design[0].count
        guard n >= p else { return [Double](repeating: 0, count: p) }

        // Initial ordinary least-squares solution
        var beta = solveWeightedLS(design: design, values: values, weights: [Double](repeating: 1.0, count: n))

        // IRLS iterations
        for _ in 0..<25 {
            var weights = [Double](repeating: 1.0, count: n)
            for i in 0..<n {
                var pred = 0.0
                for j in 0..<p {
                    pred += design[i][j] * beta[j]
                }
                let residual = values[i] - pred
                // soft-L1 weight: 1 / sqrt(1 + (r / noise)^2)
                let z = (residual * residual) / (noise * noise)
                weights[i] = 1.0 / sqrt(1.0 + z)
            }

            let newBeta = solveWeightedLS(design: design, values: values, weights: weights)

            var maxChange = 0.0
            for j in 0..<p {
                maxChange = max(maxChange, abs(newBeta[j] - beta[j]))
            }
            beta = newBeta
            if maxChange < 1e-7 {
                break
            }
        }

        return beta
    }

    /// Solves (X^T W X) beta = X^T W y for p = 2 or p = 3.
    private static func solveWeightedLS(design: [[Double]], values: [Double], weights: [Double]) -> [Double] {
        let n = design.count
        let p = design[0].count

        // Compute A = X^T W X and b = X^T W y
        var A = [Double](repeating: 0, count: p * p)
        var b = [Double](repeating: 0, count: p)

        for i in 0..<n {
            let w = weights[i]
            let y = values[i]
            for r in 0..<p {
                let x_ir = design[i][r]
                b[r] += x_ir * w * y
                for c in 0..<p {
                    A[r * p + c] += x_ir * w * design[i][c]
                }
            }
        }

        // Regularize slightly on diagonal for numerical stability
        for d in 0..<p {
            A[d * p + d] += 1e-9
        }

        if p == 2 {
            let a00 = A[0], a01 = A[1]
            let a10 = A[2], a11 = A[3]
            let det = a00 * a11 - a01 * a10
            guard abs(det) > 1e-14 else { return [0, 0] }
            let inv00 = a11 / det
            let inv01 = -a01 / det
            let inv10 = -a10 / det
            let inv11 = a00 / det
            return [
                inv00 * b[0] + inv01 * b[1],
                inv10 * b[0] + inv11 * b[1]
            ]
        } else if p == 3 {
            // Invert 3x3 matrix via adjugate
            let m00 = A[0], m01 = A[1], m02 = A[2]
            let m10 = A[3], m11 = A[4], m12 = A[5]
            let m20 = A[6], m21 = A[7], m22 = A[8]

            let c00 = m11 * m22 - m12 * m21
            let c01 = -(m10 * m22 - m12 * m20)
            let c02 = m10 * m21 - m11 * m20

            let det = m00 * c00 + m01 * c01 + m02 * c02
            guard abs(det) > 1e-14 else { return [0, 0, 0] }

            let c10 = -(m01 * m22 - m02 * m21)
            let c11 = m00 * m22 - m02 * m20
            let c12 = -(m00 * m21 - m01 * m20)

            let c20 = m01 * m12 - m02 * m11
            let c21 = -(m00 * m12 - m02 * m10)
            let c22 = m00 * m11 - m01 * m10

            let invDet = 1.0 / det
            // Transpose cofactors for inverse
            let i00 = c00 * invDet, i01 = c10 * invDet, i02 = c20 * invDet
            let i10 = c01 * invDet, i11 = c11 * invDet, i12 = c21 * invDet
            let i20 = c02 * invDet, i21 = c12 * invDet, i22 = c22 * invDet

            return [
                i00 * b[0] + i01 * b[1] + i02 * b[2],
                i10 * b[0] + i11 * b[1] + i12 * b[2],
                i20 * b[0] + i21 * b[1] + i22 * b[2]
            ]
        }

        return [Double](repeating: 0, count: p)
    }
}
