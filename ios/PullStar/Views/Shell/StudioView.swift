import SwiftUI
import UniformTypeIdentifiers
import PullStarKit

/// Port of App.tsx: header, "Alignment studio" intro with workflow steps, then the
/// two-column studio grid (image workspace left, alignment setup right).
struct StudioView: View {
    @Bindable var model: AppModel

    private enum FolderTarget { case input, output, conversion }
    @State private var folderTarget: FolderTarget?

    var body: some View {
        GeometryReader { geo in
            let wide = geo.size.width >= 1000
            let horizontalPadding: CGFloat = geo.size.width >= 1180 ? 32 : 22
            Group {
                if wide {
                    VStack(spacing: 0) {
                        StudioHeader(model: model)
                        StudioIntro(model: model, stacked: false)
                        HStack(alignment: .top, spacing: PS.gutter) {
                            GeometryReader { col in
                                ScrollViewReader { proxy in
                                    ScrollView {
                                        // Stage fills the column with the activity bar collapsed;
                                        // expanding processing details scrolls the column (as the web page does).
                                        mainColumn(stageHeight: max(420, col.size.height - 150))
                                    }
                                    .scrollIndicators(.hidden)
                                    .onChange(of: model.isTelemetryCollapsed) { _, collapsed in
                                        withAnimation(.snappy) { proxy.scrollTo(collapsed ? "stage" : "activity", anchor: collapsed ? .top : .bottom) }
                                    }
                                }
                            }
                            SetupPane(model: model, scrollsInternally: true,
                                      onChooseInput: { folderTarget = .input },
                                      onChooseOutput: { folderTarget = .output },
                                      onChooseConversion: { folderTarget = .conversion })
                                .frame(width: geo.size.width >= 1180 ? PS.setupWidth : 340)
                                .padding(.top, 32)
                        }
                        .padding(.bottom, 16)
                    }
                    .padding(.horizontal, horizontalPadding)
                } else {
                    ScrollView {
                        VStack(spacing: 0) {
                            StudioHeader(model: model)
                            StudioIntro(model: model, stacked: true)
                            mainColumn(stageHeight: 600)
                            SetupPane(model: model, scrollsInternally: false,
                                      onChooseInput: { folderTarget = .input },
                                      onChooseOutput: { folderTarget = .output },
                                      onChooseConversion: { folderTarget = .conversion })
                                .padding(.top, 24)
                        }
                        .padding(.horizontal, horizontalPadding)
                        .padding(.bottom, 24)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .safeAreaInset(edge: .bottom, spacing: 0) {
                        SetupFooter(model: model)
                            .background(.ultraThinMaterial)
                    }
                }
            }
        }
        .background(StudioBackground())
        .fileImporter(isPresented: Binding(get: { folderTarget != nil }, set: { if !$0 { folderTarget = nil } }),
                      allowedContentTypes: [.folder]) { result in
            guard case .success(let url) = result, let target = folderTarget else { return }
            switch target {
            case .input: model.chooseFolder(url)
            case .output: model.chooseOutputFolder(url)
            case .conversion: model.chooseConversionFolder(url)
            }
            folderTarget = nil
        }
        .onChange(of: model.config) { _, _ in model.persistSettings() }
    }

    @ViewBuilder
    private func mainColumn(stageHeight: CGFloat) -> some View {
        let showingResults = model.activeView == .results && model.hasResult
        VStack(alignment: .leading, spacing: 12) {
            WorkspaceCaption(model: model, showingResults: showingResults)
            Group {
                if showingResults {
                    ResultsStage(model: model)
                } else {
                    Viewfinder(model: model, onChooseFolder: { folderTarget = .input })
                }
            }
            .frame(height: showingResults ? max(stageHeight, 560) : stageHeight)
            .id("stage")

            if model.jobState.status == .failed {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Alignment needs attention").font(.system(size: 14, weight: .semibold))
                    Text(model.jobState.error ?? "The job could not complete. Review your source and settings, then try again.")
                        .font(PS.note)
                }
                .foregroundStyle(PS.danger)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(PS.danger.opacity(0.035)))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(PS.danger.opacity(0.19)))
            }
            ActivityPanel(model: model).id("activity")
            Label("Your images stay on this iPad. Alignment runs locally.", systemImage: "folder")
                .font(.system(size: 11)).foregroundStyle(Color(hex: 0x929299))
                .padding(.horizontal, 4)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Header (WorkspaceNav.tsx)

private struct StudioHeader: View {
    @Bindable var model: AppModel

    private var status: String {
        let s = model.jobState
        switch s.status {
        case .cancelling: return "Cancelling…"
        case .cancelled: return "Alignment cancelled"
        case .created, .running: return "Aligning · \(Int(s.overallProgress * 100))%"
        case .completed: return "Alignment complete"
        case .failed: return "Needs attention"
        case .idle: return "Local workspace"
        }
    }

    var body: some View {
        HStack(spacing: 20) {
            HStack(spacing: 12) {
                BrandIcon(size: 40)
                (Text("PullStar") + Text(".").foregroundStyle(Color(hex: 0x929298)))
                    .font(.system(size: 23, weight: .semibold)).tracking(-0.8)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("PullStar")
            Spacer()
            if model.hasResult {
                HStack(spacing: 4) {
                    navPill("Workspace", icon: "square.stack.3d.up", view: .workspace)
                    navPill("Results", icon: "checkmark", view: .results)
                }
                .padding(4)
                .background(Capsule().fill(Color.white.opacity(0.03)))
                .overlay(Capsule().strokeBorder(Color.white.opacity(0.1)))
                Spacer()
            }
            HStack(spacing: 8) {
                if model.isProcessing { ProgressView().controlSize(.mini).tint(Color(hex: 0xb4b4b9)) }
                else if model.jobState.status == .failed { Image(systemName: "exclamationmark.circle") }
                else { StatusDot() }
                Text(status)
            }
            .font(.system(size: 13))
            .foregroundStyle(model.jobState.status == .failed ? PS.danger : Color(hex: 0xb4b4b9))
            .accessibilityAddTraits(.updatesFrequently)
        }
        .frame(height: 60)
        .overlay(alignment: .bottom) { Rectangle().fill(Color.white.opacity(0.05)).frame(height: 1) }
    }

    private func navPill(_ title: String, icon: String, view: WorkspaceView) -> some View {
        let active = model.activeView == view
        return Button { withAnimation(.snappy) { model.activeView = view } } label: {
            Label(title, systemImage: icon).font(.system(size: 13, weight: active ? .medium : .regular))
                .padding(.horizontal, 16).frame(minHeight: 38)
                .foregroundStyle(active ? Color(hex: 0xf0f0f2) : Color(hex: 0xa9a9af))
                .background(Capsule().fill(active ? Color.white.opacity(0.08) : .clear))
                .overlay(Capsule().strokeBorder(Color.white.opacity(active ? 0.16 : 0)))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .hoverEffect(.highlight)
        .accessibilityAddTraits(active ? .isSelected : [])
    }
}

// MARK: - Intro with workflow steps

private struct StudioIntro: View {
    @Bindable var model: AppModel
    var stacked: Bool

    var body: some View {
        let layout = stacked ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12)) : AnyLayout(HStackLayout(spacing: 16))
        layout {
            Text("Alignment studio").font(.system(size: 18)).tracking(-0.3).foregroundStyle(Color(hex: 0xb4b4bd))
            if !stacked { Spacer() }
            WorkflowSteps(model: model)
        }
        .padding(.vertical, stacked ? 14 : 10)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct WorkflowSteps: View {
    @Bindable var model: AppModel

    var body: some View {
        let loaded = !model.sequence.isEmpty
        let referenced = model.config.polaris != nil || model.hasResult
        HStack(spacing: 12) {
            step("01", "Load frames", done: loaded, current: !loaded)
            arrow
            step("02", "References (optional)", done: referenced, current: loaded && !referenced)
            arrow
            step("03", "Align & export", done: model.hasResult, current: model.isProcessing)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Alignment workflow")
    }

    private var arrow: some View {
        Image(systemName: "arrow.right").font(.system(size: 11)).foregroundStyle(PS.textDim)
    }

    private func step(_ number: String, _ title: String, done: Bool, current: Bool) -> some View {
        HStack(spacing: 8) {
            ZStack {
                Circle().fill(current ? Color.white.opacity(0.08) : .clear)
                Circle().strokeBorder(Color.white.opacity(current ? 0.25 : 0.094))
                if done { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)) }
                else { Text(number).font(.system(size: 11).monospacedDigit()) }
            }
            .frame(width: 28, height: 28)
            Text(title).font(.system(size: 13)).fixedSize()
        }
        .foregroundStyle(done ? PS.success : current ? Color(hex: 0xe5e5e7) : PS.textDim)
    }
}

// MARK: - Caption above the stage

private struct WorkspaceCaption: View {
    @Bindable var model: AppModel
    let showingResults: Bool

    var body: some View {
        HStack(spacing: 12) {
            Label {
                Text(showingResults ? (model.config.noStack ? "Your aligned images" : "Your aligned stack") : "Image workspace")
                    .font(.system(size: 14))
            } icon: {
                Image(systemName: "scope").foregroundStyle(Color(hex: 0xa0a0a7))
            }
            Spacer()
            Text(model.sequence.isEmpty
                 ? "Original pixels. Precise alignment."
                 : "\(model.sequence.count) frames · \(model.config.inputDirectory.lastPathComponent)")
                .font(.system(size: 12)).foregroundStyle(Color(hex: 0x909097)).lineLimit(1).truncationMode(.middle)
        }
        .frame(height: 20)
    }
}

private struct StudioBackground: View {
    var body: some View {
        ZStack {
            PS.workspace
            RadialGradient(colors: [Color.white.opacity(0.028), .clear], center: UnitPoint(x: 0.8, y: -0.1), startRadius: 0, endRadius: 700)
            RadialGradient(colors: [Color.white.opacity(0.012), .clear], center: UnitPoint(x: 0, y: 0.5), startRadius: 0, endRadius: 500)
        }
        .ignoresSafeArea()
    }
}
