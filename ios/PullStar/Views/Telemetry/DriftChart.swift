import SwiftUI

public struct DriftPoint: Identifiable, Sendable, Equatable {
    public let id = UUID()
    public let x: Double
    public let y: Double

    public init(x: Double, y: Double) {
        self.x = x
        self.y = y
    }
}

/// Dynamic dual-line chart visualizing measured star tracking drift (X & Y axes).
public struct DriftChart: View {
    public let points: [DriftPoint]
    public let xColor = Color(red: 0.557, green: 0.788, blue: 0.820) // #8ec9d1
    public let yColor = Color(red: 0.808, green: 0.718, blue: 0.569) // #ceb791

    public init(points: [DriftPoint]) {
        self.points = points
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Chart header
            HStack {
                Text("Tracking precision")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Color(white: 0.65))

                Spacer()

                if let latest = points.last {
                    HStack(spacing: 8) {
                        HStack(spacing: 4) {
                            Circle().fill(xColor).frame(width: 5, height: 5)
                            Text(String(format: "X %+.2f px", latest.x))
                                .font(.system(size: 11, weight: .medium, design: .monospaced))
                                .foregroundColor(xColor)
                        }

                        HStack(spacing: 4) {
                            Circle().fill(yColor).frame(width: 5, height: 5)
                            Text(String(format: "Y %+.2f px", latest.y))
                                .font(.system(size: 11, weight: .medium, design: .monospaced))
                                .foregroundColor(yColor)
                        }
                    }
                } else {
                    Text("Waiting for measured drift")
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                        .foregroundColor(Color(white: 0.4))
                }
            }

            // Chart area
            ZStack {
                // Background surface
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color(red: 0.03, green: 0.03, blue: 0.03))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .stroke(Color.white.opacity(0.06), lineWidth: 1)
                    )

                // Zero line
                GeometryReader { geo in
                    Path { path in
                        path.move(to: CGPoint(x: 0, y: geo.size.height / 2))
                        path.addLine(to: CGPoint(x: geo.size.width, y: geo.size.height / 2))
                    }
                    .stroke(
                        Color.white.opacity(0.12),
                        style: StrokeStyle(lineWidth: 1, dash: [4, 4])
                    )
                }

                if points.count >= 2 {
                    GeometryReader { geo in
                        let w = geo.size.width
                        let h = geo.size.height
                        let midY = h / 2

                        // Scale drift: 1px drift = 8pt offset, clamped
                        let maxDrift: CGFloat = 5.0
                        let scaleFactor = (h / 2) / maxDrift

                        // X-drift curve
                        Path { path in
                            for (i, p) in points.enumerated() {
                                let x = (CGFloat(i) * w) / CGFloat(max(1, points.count - 1))
                                let y = midY - CGFloat(p.x) * scaleFactor
                                let clampedY = min(max(4, y), h - 4)
                                if i == 0 {
                                    path.move(to: CGPoint(x: x, y: clampedY))
                                } else {
                                    path.addLine(to: CGPoint(x: x, y: clampedY))
                                }
                            }
                        }
                        .stroke(xColor, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))

                        // Y-drift curve
                        Path { path in
                            for (i, p) in points.enumerated() {
                                let x = (CGFloat(i) * w) / CGFloat(max(1, points.count - 1))
                                let y = midY - CGFloat(p.y) * scaleFactor
                                let clampedY = min(max(4, y), h - 4)
                                if i == 0 {
                                    path.move(to: CGPoint(x: x, y: clampedY))
                                } else {
                                    path.addLine(to: CGPoint(x: x, y: clampedY))
                                }
                            }
                        }
                        .stroke(yColor, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                    }
                } else {
                    Text("Drift measurements will appear here when star tracking begins.")
                        .font(.system(size: 11, weight: .regular))
                        .foregroundColor(Color(white: 0.35))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 16)
                }
            }
            .frame(height: 70)
        }
    }
}
