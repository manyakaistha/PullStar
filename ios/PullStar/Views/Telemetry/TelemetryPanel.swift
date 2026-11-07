import SwiftUI
import PullStarKit

public struct TelemetryPanel: View {
    public let state: JobState
    public var isCollapsed: Bool = false
    public var onToggleCollapse: (() -> Void)? = nil
    public var onCancel: (() -> Void)? = nil

    @State private var driftHistory: [DriftPoint] = []

    public init(
        state: JobState,
        isCollapsed: Bool = false,
        onToggleCollapse: (() -> Void)? = nil,
        onCancel: (() -> Void)? = nil
    ) {
        self.state = state
        self.isCollapsed = isCollapsed
        self.onToggleCollapse = onToggleCollapse
        self.onCancel = onCancel
    }

    public struct DisplayStage: Identifiable, Sendable {
        public let id: JobStage
        public let label: String

        public init(id: JobStage, label: String) {
            self.id = id
            self.label = label
        }
    }

    private var activeStages: [DisplayStage] {
        var stages: [DisplayStage] = [
            DisplayStage(id: .preparation, label: "Prepare"),
            DisplayStage(id: .pass1, label: "Track stars"),
            DisplayStage(id: .cropCalc, label: "Calculate crop"),
            DisplayStage(id: .pass2, label: "Stack frames")
        ]
        if state.videoURL != nil {
            stages.append(DisplayStage(id: .videoRender, label: "Render video"))
        }
        return stages
    }

    private var isRunning: Bool {
        state.status.isActive
    }

    private var statusTitle: String {
        switch state.status {
        case .cancelling:
            return "Cancelling alignment…"
        case .cancelled:
            return "Alignment cancelled"
        case .completed:
            return "Alignment complete"
        case .failed:
            return "Alignment stopped"
        case .running, .created:
            if let stage = state.stage {
                return activeStages.first(where: { $0.id == stage })?.label ?? "Aligning frames"
            }
            return "Aligning frames"
        case .idle:
            return "Ready for your first alignment"
        }
    }

    private var etaString: String? {
        guard isRunning, state.framesPerSecond > 0, state.total > state.current else { return nil }
        let remainingFrames = Double(state.total - state.current)
        let remainingSeconds = remainingFrames / state.framesPerSecond
        if remainingSeconds < 60 {
            return String(format: "~%.0fs remaining", remainingSeconds)
        } else {
            let minutes = Int(remainingSeconds / 60)
            let seconds = Int(remainingSeconds) % 60
            return String(format: "~%dm %02ds remaining", minutes, seconds)
        }
    }

    public var body: some View {
        VStack(spacing: 10) {
            // Error banner if any
            if let error = state.error, !error.isEmpty {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(Color(red: 0.94, green: 0.44, blue: 0.44))
                        .font(.system(size: 14))

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Processing Error")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                        Text(error)
                            .font(.system(size: 11, weight: .regular, design: .monospaced))
                            .foregroundColor(Color(red: 0.94, green: 0.65, blue: 0.65))
                            .lineLimit(3)
                    }

                    Spacer()
                }
                .padding(10)
                .background(Color(red: 0.3, green: 0.05, blue: 0.05).opacity(0.85))
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(Color(red: 0.94, green: 0.44, blue: 0.44).opacity(0.4), lineWidth: 1)
                )
            }

            // Summary Header
            HStack(alignment: .center, spacing: 10) {
                // Icon
                ZStack {
                    Circle()
                        .fill(statusBackgroundColor)
                        .frame(width: 32, height: 32)

                    if state.status == .running {
                        ProgressView()
                            .scaleEffect(0.7)
                            .tint(Color(red: 0.22, green: 0.74, blue: 0.97))
                    } else if state.status == .completed {
                        Image(systemName: "checkmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(Color(red: 0.20, green: 0.83, blue: 0.60))
                    } else if state.status == .failed {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(Color(red: 0.94, green: 0.44, blue: 0.44))
                    } else {
                        Image(systemName: "waveform.path.ecg")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundColor(Color(white: 0.7))
                    }
                }

                // Title and Subtext
                VStack(alignment: .leading, spacing: 2) {
                    Text(statusTitle)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(.white)

                    HStack(spacing: 6) {
                        if isRunning {
                            let stagePercent = Int(round(state.progress * 100))
                            Text("\(stagePercent)% of this stage")
                                .font(.system(size: 11, weight: .medium, design: .monospaced))
                                .foregroundColor(Color(white: 0.75))

                            if state.total > 0 {
                                Text("·")
                                    .foregroundColor(Color(white: 0.4))
                                Text("\(state.current) / \(state.total) steps")
                                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                                    .foregroundColor(Color(white: 0.65))
                            }

                            if state.framesPerSecond > 0 {
                                Text("·")
                                    .foregroundColor(Color(white: 0.4))
                                Text(String(format: "%.1f fps", state.framesPerSecond))
                                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                            }

                            if let eta = etaString {
                                Text("·")
                                    .foregroundColor(Color(white: 0.4))
                                Text(eta)
                                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                                    .foregroundColor(Color(white: 0.6))
                            }
                        } else {
                            Text("Processing activity")
                                .font(.system(size: 11, weight: .regular))
                                .foregroundColor(Color(white: 0.5))
                        }
                    }
                }

                Spacer()

                // Overall percentage & Cancel Button
                HStack(spacing: 12) {
                    if isRunning {
                        let overallPercent = Int(state.overallProgress * 100)
                        VStack(alignment: .trailing, spacing: 0) {
                            Text("\(overallPercent)%")
                                .font(.system(size: 15, weight: .bold, design: .monospaced))
                                .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                            Text("overall")
                                .font(.system(size: 9, weight: .regular))
                                .foregroundColor(Color(white: 0.5))
                        }

                        // Cancel Button
                        if let onCancel {
                            Button(action: onCancel) {
                                HStack(spacing: 4) {
                                    if state.status == .cancelling {
                                        ProgressView()
                                            .scaleEffect(0.6)
                                            .tint(.white)
                                    } else {
                                        Image(systemName: "stop.fill")
                                            .font(.system(size: 9, weight: .bold))
                                    }
                                    Text(state.status == .cancelling ? "Cancelling…" : "Cancel")
                                        .font(.system(size: 11, weight: .semibold))
                                }
                                .foregroundColor(.white)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 5)
                                .background(Color(red: 0.85, green: 0.2, blue: 0.2).opacity(0.8))
                                .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                            .disabled(state.status == .cancelling)
                        }
                    }

                    // Collapse toggle chevron
                    if let onToggleCollapse {
                        Button(action: onToggleCollapse) {
                            Image(systemName: "chevron.down")
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundColor(Color(white: 0.6))
                                .rotationEffect(isCollapsed ? .degrees(0) : .degrees(180))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            // Overall Progress Bar (animated gradient)
            if isRunning {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 3)
                            .fill(Color(white: 0.1))
                            .frame(height: 6)

                        RoundedRectangle(cornerRadius: 3)
                            .fill(
                                LinearGradient(
                                    colors: [Color(red: 0.15, green: 0.45, blue: 0.95), Color(red: 0.25, green: 0.75, blue: 0.98)],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                            .frame(width: max(0, min(geo.size.width * CGFloat(state.overallProgress), geo.size.width)), height: 6)
                            .shadow(color: Color(red: 0.25, green: 0.75, blue: 0.98).opacity(0.5), radius: 4, x: 0, y: 0)
                            .animation(.spring(response: 0.3), value: state.overallProgress)
                    }
                }
                .frame(height: 6)
            }

            // Expanded details
            if !isCollapsed {
                VStack(spacing: 12) {
                    // 1. Pipeline Stages with LEDs
                    HStack(spacing: 6) {
                        ForEach(Array(activeStages.enumerated()), id: \.element.id) { index, stage in
                            StageLEDItem(
                                stage: stage,
                                index: index,
                                currentStage: state.stage,
                                isCompleted: state.status == .completed || isStageCompleted(stage: stage.id),
                                isCurrent: isRunning && state.stage == stage.id
                            )
                        }
                    }

                    // 2. Drift Chart
                    DriftChart(points: driftHistory)

                    // 3. Hardware Compute Info
                    if !state.computeDescription.isEmpty {
                        HStack {
                            Text("Processing hardware")
                                .font(.system(size: 11, weight: .regular))
                                .foregroundColor(Color(white: 0.5))

                            Spacer()

                            Text(state.computeDescription)
                                .font(.system(size: 11, weight: .medium, design: .monospaced))
                                .foregroundColor(Color(white: 0.8))
                        }
                        .padding(.horizontal, 4)
                    }
                }
                .padding(.top, 4)
            }
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(red: 0.07, green: 0.07, blue: 0.08).opacity(0.9))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.35), radius: 12, x: 0, y: 4)
        .onChange(of: state.driftX) { _, newX in
            updateDrift(x: newX, y: state.driftY)
        }
        .onChange(of: state.driftY) { _, newY in
            updateDrift(x: state.driftX, y: newY)
        }
    }

    private var statusBackgroundColor: Color {
        switch state.status {
        case .completed:
            return Color(red: 0.20, green: 0.83, blue: 0.60).opacity(0.15)
        case .failed:
            return Color(red: 0.94, green: 0.44, blue: 0.44).opacity(0.15)
        case .running, .cancelling:
            return Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.15)
        default:
            return Color.white.opacity(0.06)
        }
    }

    private func isStageCompleted(stage: JobStage) -> Bool {
        guard let current = state.stage else { return false }
        let order: [JobStage] = [.preparation, .conversion, .pass1, .cropCalc, .pass2, .videoRender, .done]
        guard let currentIdx = order.firstIndex(of: current),
              let stageIdx = order.firstIndex(of: stage) else { return false }
        return stageIdx < currentIdx
    }

    private func updateDrift(x: Double, y: Double) {
        if state.status == .idle || state.stage == .preparation {
            driftHistory.removeAll()
        } else if x != 0 || y != 0 || !driftHistory.isEmpty {
            driftHistory.append(DriftPoint(x: x, y: y))
            if driftHistory.count > 60 {
                driftHistory.removeFirst(driftHistory.count - 60)
            }
        }
    }
}

/// An individual stage pill with LED indicator.
private struct StageLEDItem: View {
    let stage: TelemetryPanel.DisplayStage
    let index: Int
    let currentStage: JobStage?
    let isCompleted: Bool
    let isCurrent: Bool

    var body: some View {
        HStack(spacing: 6) {
            // LED circle / Icon
            ZStack {
                if isCompleted {
                    Circle()
                        .fill(Color(red: 0.20, green: 0.83, blue: 0.60))
                        .frame(width: 14, height: 14)
                    Image(systemName: "checkmark")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(.black)
                } else if isCurrent {
                    Circle()
                        .fill(Color(red: 0.22, green: 0.74, blue: 0.97))
                        .frame(width: 14, height: 14)
                        .shadow(color: Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.8), radius: 4, x: 0, y: 0)
                    Circle()
                        .fill(Color.white)
                        .frame(width: 4, height: 4)
                } else {
                    Circle()
                        .fill(Color(white: 0.16))
                        .frame(width: 14, height: 14)
                    Text("\(index + 1)")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(Color(white: 0.45))
                }
            }

            Text(stage.label)
                .font(.system(size: 11, weight: isCurrent ? .bold : .medium))
                .foregroundColor(isCompleted ? Color(white: 0.9) : isCurrent ? .white : Color(white: 0.45))
                .lineLimit(1)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(isCurrent ? Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.12) : isCompleted ? Color(white: 0.08) : Color(white: 0.04))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(isCurrent ? Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.3) : Color.white.opacity(0.04), lineWidth: 1)
        )
    }
}

// MARK: - Telemetry Previews

#if DEBUG
#Preview("Telemetry Running") {
    var state = JobState()
    state.status = .running
    state.stage = .pass1
    state.progress = 0.65
    state.overallProgress = 0.42
    state.current = 84
    state.total = 200
    state.driftX = 1.45
    state.driftY = -0.82
    state.framesPerSecond = 24.8
    state.computeDescription = "Apple Neural Engine & Metal GPU · 8 CPU workers"

    return TelemetryPanel(state: state)
        .padding()
        .background(Color.black)
}

#Preview("Telemetry Completed") {
    var state = JobState()
    state.status = .completed
    state.stage = .done
    state.overallProgress = 1.0
    state.current = 200
    state.total = 200
    state.frameCount = 200
    state.resultURL = URL(fileURLWithPath: "/tmp/aligned_output.tif")
    state.computeDescription = "Apple Neural Engine & Metal GPU · 8 CPU workers"

    return TelemetryPanel(state: state)
        .padding()
        .background(Color.black)
}
#endif
