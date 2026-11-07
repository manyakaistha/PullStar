import SwiftUI
import PullStarKit

/// Port of LiveTelemetry.tsx (the collapsible "Processing activity" bar).
struct ActivityPanel: View {
    @Bindable var model: AppModel
    @State private var points: [CGPoint] = []

    private var state: JobState { model.jobState }
    private var running: Bool { state.status.isActive }

    private var stages: [(JobStage, String)] {
        var list: [(JobStage, String)] = [(.preparation, "Prepare")]
        if model.config.conversionFormat != .none { list.append((.conversion, "Convert frames")) }
        list += [(.pass1, "Track stars"), (.cropCalc, "Calculate crop"), (.pass2, model.config.noStack ? "Export images" : "Stack frames")]
        if model.config.videoEnabled && !model.config.noStack { list.append((.videoRender, "Render video")) }
        return list
    }

    private var title: String {
        switch state.status {
        case .cancelling: "Cancelling alignment…"
        case .cancelled: "Alignment cancelled"
        case .completed: "Alignment complete"
        case .failed: "Alignment stopped"
        case .created, .running: stages.first(where: { $0.0 == state.stage })?.1 ?? "Aligning frames"
        case .idle: "Ready for your first alignment"
        }
    }

    private var subtitle: String {
        guard running else { return "Processing activity" }
        var parts = ["\(Int((state.progress * 100).rounded()))% of this stage"]
        if state.total > 0 { parts.append("\(state.current) / \(state.total) steps") }
        if state.framesPerSecond > 0 { parts.append(String(format: "%.1f fps", state.framesPerSecond)) }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            summary
            if running {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Color.white.opacity(0.035))
                        Capsule().fill(Color(hex: 0xd7d7e0)).frame(width: geo.size.width * min(1, max(0, state.overallProgress)))
                            .animation(.easeOut(duration: 0.18), value: state.overallProgress)
                    }
                }
                .frame(height: 5)
                .padding(.top, 16)
                .accessibilityElement()
                .accessibilityLabel("Alignment progress")
                .accessibilityValue("\(Int(state.overallProgress * 100)) percent")
            }
            if !model.isTelemetryCollapsed { details.transition(.opacity.combined(with: .move(edge: .top))) }
        }
        .padding(.horizontal, 20).padding(.vertical, 16)
        .glassSurface(radius: 20)
        .onChange(of: state.driftX) { _, _ in recordDrift() }
        .onChange(of: state.driftY) { _, _ in recordDrift() }
        .onChange(of: state.stage) { _, stage in if stage == .preparation { points = [] } }
    }

    private var summary: some View {
        HStack(spacing: 14) {
            Group {
                if running { ProgressView().controlSize(.small).tint(Color(hex: 0xb5b5bd)) }
                else { Image(systemName: state.status == .failed ? "exclamationmark.circle" : "waveform.path.ecg").font(.system(size: 18)) }
            }
            .frame(width: 22)
            .foregroundStyle(state.status == .failed ? PS.danger : Color(hex: 0xb5b5bd))
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.system(size: 15, weight: .medium)).foregroundStyle(Color(hex: 0xd9d9df))
                Text(subtitle).font(PS.caption).foregroundStyle(Color(hex: 0x8e8e97))
            }
            Spacer(minLength: 8)
            if running {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text("\(Int(state.overallProgress * 100))%").font(.system(size: 18).monospacedDigit())
                    Text("overall").font(.system(size: 11)).foregroundStyle(Color(hex: 0xaaaab4))
                }
            }
            Button {
                withAnimation(.snappy(duration: 0.25)) { model.isTelemetryCollapsed.toggle() }
            } label: {
                Image(systemName: "chevron.down").font(.system(size: 14, weight: .semibold))
                    .rotationEffect(.degrees(model.isTelemetryCollapsed ? 0 : 180))
                    .frame(width: 44, height: 44)
                    .background(Circle().fill(Color.white.opacity(0.016)))
                    .overlay(Circle().strokeBorder(Color.white.opacity(0.08)))
                    .foregroundStyle(Color(hex: 0xbfbfc7))
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .hoverEffect(.highlight)
            .accessibilityLabel(model.isTelemetryCollapsed ? "Show processing details" : "Hide processing details")
        }
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: 18) {
            if !state.computeDescription.isEmpty || !model.hardwareSummary.isEmpty {
                HStack(spacing: 16) {
                    Text("Processing hardware").foregroundStyle(Color(hex: 0xa1a1aa))
                    Text(state.computeDescription.isEmpty ? model.hardwareSummary : state.computeDescription).fontWeight(.medium)
                }
                .font(.system(size: 13))
            }
            stageRow
            driftChart
        }
        .padding(.top, 22)
    }

    private var stageRow: some View {
        let activeIndex = stages.firstIndex(where: { $0.0 == state.stage }) ?? -1
        return ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { stageItems(activeIndex); }
            VStack(alignment: .leading, spacing: 10) { stageItems(activeIndex) }
        }
    }

    @ViewBuilder private func stageItems(_ activeIndex: Int) -> some View {
        ForEach(Array(stages.enumerated()), id: \.offset) { i, stage in
            let done = state.status == .completed || i < activeIndex
            let current = running && i == activeIndex
            HStack(spacing: 7) {
                ZStack {
                    Circle().strokeBorder(Color.white.opacity(current ? 0.3 : 0.086))
                    if done { Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)) }
                    else { Text("\(i + 1)").font(.system(size: 11).monospacedDigit()) }
                }
                .frame(width: 26, height: 26)
                Text(stage.1).font(.system(size: 13)).fixedSize()
            }
            .foregroundStyle(done ? PS.success : current ? Color(hex: 0xefeff4) : Color(hex: 0x8b8b96))
            if i < stages.count - 1 { Spacer(minLength: 0) }
        }
    }

    private var driftChart: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Tracking precision").font(.system(size: 13)).foregroundStyle(Color(hex: 0xaaaab4))
                Spacer()
                Text(points.last.map { String(format: "X %.2f px · Y %.2f px", $0.x, $0.y) } ?? "Waiting for measured drift")
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(Color(hex: 0x8c8c98))
            }
            if points.isEmpty {
                Text("Drift measurements will appear here when star tracking begins.")
                    .font(PS.caption).foregroundStyle(Color(hex: 0x95959f))
            } else {
                Canvas { ctx, size in
                    let mid = size.height / 2
                    var axis = Path(); axis.move(to: CGPoint(x: 0, y: mid)); axis.addLine(to: CGPoint(x: size.width, y: mid))
                    ctx.stroke(axis, with: .color(.white.opacity(0.094)), style: StrokeStyle(lineWidth: 1, dash: [3, 5]))
                    let step = size.width / CGFloat(max(1, points.count - 1))
                    let k = size.height / 80 * 8
                    for (keyPath, color) in [(\CGPoint.x, PS.driftX), (\CGPoint.y, PS.driftY)] {
                        var path = Path()
                        for (i, p) in points.enumerated() {
                            let pt = CGPoint(x: CGFloat(i) * step, y: min(size.height - 1, max(1, mid - p[keyPath: keyPath] * k)))
                            i == 0 ? path.move(to: pt) : path.addLine(to: pt)
                        }
                        ctx.stroke(path, with: .color(color), lineWidth: 1.5)
                    }
                }
                .frame(height: 76)
                .clipped()
                .accessibilityLabel("Measured horizontal and vertical star drift")
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.black.opacity(0.25)))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.white.opacity(0.047)))
    }

    private func recordDrift() {
        guard running, state.stage != .preparation else { return }
        points.append(CGPoint(x: state.driftX, y: state.driftY))
        if points.count > 60 { points.removeFirst(points.count - 60) }
    }
}
