import Foundation
import CoreGraphics

/// Kalman filter and smoother for 2D position/translation tracking.
///
/// Uses a constant velocity state vector [x, y, vx, vy] to predict positions,
/// smooth out high-frequency camera shake / jitter from wind, and reject
/// measurement outliers (e.g. clouds, satellites, cosmic rays).
public final class KalmanSmoother: @unchecked Sendable {
    public var processNoise: Double
    public var measurementNoise: Double

    // State: [x, y, vx, vy]
    private var state: (x: Double, y: Double, vx: Double, vy: Double) = (0, 0, 0, 0)

    // 4x4 Covariance Matrix P (stored as row-major array of 16 elements)
    private var P: [Double] = [
        10, 0, 0, 0,
        0, 10, 0, 0,
        0, 0, 10, 0,
        0, 0, 0, 10
    ]

    private var _isInitialized = false
    public var isInitialized: Bool { _isInitialized }

    public init(processNoise: Double = 0.01, measurementNoise: Double = 2.0) {
        self.processNoise = processNoise
        self.measurementNoise = measurementNoise
        reset()
    }

    public func reset() {
        state = (0, 0, 0, 0)
        P = [
            10, 0, 0, 0,
            0, 10, 0, 0,
            0, 0, 10, 0,
            0, 0, 0, 10
        ]
        _isInitialized = false
    }

    public func initialize(at position: CGPoint) {
        state = (Double(position.x), Double(position.y), 0.0, 0.0)
        P = [
            10, 0, 0, 0,
            0, 10, 0, 0,
            0, 0, 10, 0,
            0, 0, 0, 10
        ]
        _isInitialized = true
    }

    /// Predict next state: X' = F @ X; P' = F @ P @ F^T + Q
    @discardableResult
    public func predict() -> CGPoint {
        guard _isInitialized else {
            return .zero
        }

        // State update: x' = x + vx, y' = y + vy, vx' = vx, vy' = vy
        let newX = state.x + state.vx
        let newY = state.y + state.vy
        state.x = newX
        state.y = newY

        // Covariance update: P' = F @ P @ F^T + Q
        // F = [1 0 1 0; 0 1 0 1; 0 0 1 0; 0 0 0 1]
        let p00 = P[0],  p01 = P[1],  p02 = P[2],  p03 = P[3]
        let p10 = P[4],  p11 = P[5],  p12 = P[6],  p13 = P[7]
        let p20 = P[8],  p21 = P[9],  p22 = P[10], p23 = P[11]
        let p30 = P[12], p31 = P[13], p32 = P[14], p33 = P[15]

        let q = processNoise

        P[0]  = p00 + p02 + p20 + p22 + q
        P[1]  = p01 + p03 + p21 + p23
        P[2]  = p02 + p22
        P[3]  = p03 + p23

        P[4]  = p10 + p12 + p30 + p32
        P[5]  = p11 + p13 + p31 + p33 + q
        P[6]  = p12 + p32
        P[7]  = p13 + p33

        P[8]  = p20 + p22
        P[9]  = p21 + p23
        P[10] = p22 + q
        P[11] = p23

        P[12] = p30 + p32
        P[13] = p31 + p33
        P[14] = p32
        P[15] = p33 + q

        return CGPoint(x: state.x, y: state.y)
    }

    /// Calculate Mahalanobis distance (chi-squared, 2 DOF) for outlier detection.
    public func innovation(for measured: CGPoint) -> Double {
        guard _isInitialized else { return 0.0 }

        let y0 = Double(measured.x) - state.x
        let y1 = Double(measured.y) - state.y

        // S = H @ P @ H^T + R
        let s00 = P[0] + measurementNoise
        let s01 = P[1]
        let s10 = P[4]
        let s11 = P[5] + measurementNoise

        let det = s00 * s11 - s01 * s10
        guard abs(det) > 1e-12 else { return 0.0 }

        // inv(S) = (1/det) * [s11 -s01; -s10 s00]
        let invS00 = s11 / det
        let invS01 = -s01 / det
        let invS10 = -s10 / det
        let invS11 = s00 / det

        let mahalanobis = y0 * (invS00 * y0 + invS01 * y1) + y1 * (invS10 * y0 + invS11 * y1)
        return max(0.0, mahalanobis)
    }

    /// Incorporate a measurement and return the updated filtered position.
    @discardableResult
    public func update(with measured: CGPoint) -> CGPoint {
        guard _isInitialized else {
            initialize(at: measured)
            return measured
        }

        let z0 = Double(measured.x)
        let z1 = Double(measured.y)

        let y0 = z0 - state.x
        let y1 = z1 - state.y

        // S = H @ P @ H^T + R
        let s00 = P[0] + measurementNoise
        let s01 = P[1]
        let s10 = P[4]
        let s11 = P[5] + measurementNoise

        let det = s00 * s11 - s01 * s10
        guard abs(det) > 1e-12 else {
            return CGPoint(x: state.x, y: state.y)
        }

        let invS00 = s11 / det
        let invS01 = -s01 / det
        let invS10 = -s10 / det
        let invS11 = s00 / det

        // K = P @ H^T @ inv(S) -> 4x2 matrix
        // P @ H^T is the first two columns of P
        var K = [Double](repeating: 0, count: 8) // rows: 4, cols: 2
        for i in 0..<4 {
            let p_i0 = P[i * 4 + 0]
            let p_i1 = P[i * 4 + 1]
            K[i * 2 + 0] = p_i0 * invS00 + p_i1 * invS10
            K[i * 2 + 1] = p_i0 * invS01 + p_i1 * invS11
        }

        // State update: X = X + K @ y
        state.x  += K[0] * y0 + K[1] * y1
        state.y  += K[2] * y0 + K[3] * y1
        state.vx += K[4] * y0 + K[5] * y1
        state.vy += K[6] * y0 + K[7] * y1

        // Covariance update using Joseph form:
        // P = (I - K @ H) @ P @ (I - K @ H)^T + K @ R @ K^T
        var I_KH = [Double](repeating: 0, count: 16)
        for r in 0..<4 {
            for c in 0..<4 {
                let identity = (r == c) ? 1.0 : 0.0
                let kh: Double
                if c == 0 {
                    kh = K[r * 2 + 0]
                } else if c == 1 {
                    kh = K[r * 2 + 1]
                } else {
                    kh = 0.0
                }
                I_KH[r * 4 + c] = identity - kh
            }
        }

        // Temp = (I - KH) @ P
        var temp = [Double](repeating: 0, count: 16)
        for r in 0..<4 {
            for c in 0..<4 {
                var sum = 0.0
                for k in 0..<4 {
                    sum += I_KH[r * 4 + k] * P[k * 4 + c]
                }
                temp[r * 4 + c] = sum
            }
        }

        // New P = Temp @ (I - KH)^T + K @ R @ K^T
        var newP = [Double](repeating: 0, count: 16)
        let r_noise = measurementNoise
        for r in 0..<4 {
            for c in 0..<4 {
                var sum = 0.0
                for k in 0..<4 {
                    sum += temp[r * 4 + k] * I_KH[c * 4 + k]
                }
                let k_r0 = K[r * 2 + 0]
                let k_r1 = K[r * 2 + 1]
                let k_c0 = K[c * 2 + 0]
                let k_c1 = K[c * 2 + 1]
                let krk = (k_r0 * k_c0 + k_r1 * k_c1) * r_noise
                newP[r * 4 + c] = sum + krk
            }
        }
        P = newP

        return CGPoint(x: state.x, y: state.y)
    }

    public func currentPosition() -> CGPoint {
        CGPoint(x: state.x, y: state.y)
    }

    public func currentVelocity() -> CGPoint {
        CGPoint(x: state.vx, y: state.vy)
    }

    /// Batch smoother for an entire sequence of 2D translation points.
    public static func smooth(
        points: [CGPoint],
        processNoise: Double = 0.01,
        measurementNoise: Double = 2.0
    ) -> [CGPoint] {
        guard !points.isEmpty else { return [] }
        guard points.count > 1 else { return points }

        let filter = KalmanSmoother(processNoise: processNoise, measurementNoise: measurementNoise)
        filter.initialize(at: points[0])

        var forward: [CGPoint] = [points[0]]
        for i in 1..<points.count {
            filter.predict()
            let raw = points[i]
            let innov = filter.innovation(for: raw)
            if innov > 15.0 {
                // Outlier: use prediction
                forward.append(filter.currentPosition())
            } else {
                let smoothed = filter.update(with: raw)
                forward.append(smoothed)
            }
        }

        // Backward pass (RTS-like smoothing for zero-phase trajectory)
        let backwardFilter = KalmanSmoother(processNoise: processNoise, measurementNoise: measurementNoise)
        backwardFilter.initialize(at: forward[points.count - 1])
        var backward: [CGPoint] = [CGPoint](repeating: .zero, count: points.count)
        backward[points.count - 1] = forward[points.count - 1]

        for i in stride(from: points.count - 2, through: 0, by: -1) {
            backwardFilter.predict()
            let pt = forward[i]
            let smoothed = backwardFilter.update(with: pt)
            backward[i] = smoothed
        }

        // Combine forward and backward for zero-phase smoothing
        return (0..<points.count).map { i in
            CGPoint(
                x: (forward[i].x + backward[i].x) * 0.5,
                y: (forward[i].y + backward[i].y) * 0.5
            )
        }
    }
}
