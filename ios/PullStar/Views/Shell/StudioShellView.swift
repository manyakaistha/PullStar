import SwiftUI
import PullStarKit

public struct StudioShellView: View {
    @Bindable public var model: AppModel

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @State private var showingCompactSetup = false
    @State private var showingFolderPicker = false

    public init(model: AppModel) {
        self.model = model
    }

    public var body: some View {
        Group {
            if horizontalSizeClass == .compact {
                // Adaptive layout for compact Split View / Slide Over
                compactLayout
            } else {
                // Regular iPad landscape / Stage Manager layout
                regularSplitLayout
            }
        }
        .fileImporter(
            isPresented: $showingFolderPicker,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                model.chooseFolder(url)
            }
        }
    }

    // MARK: - Regular Split View Layout
    private var regularSplitLayout: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SetupView(model: model)
                .navigationSplitViewColumnWidth(min: 320, ideal: 360, max: 420)
                .navigationBarHidden(true)
        } detail: {
            detailStage
                .navigationBarHidden(true)
        }
        .navigationSplitViewStyle(.balanced)
        .toolbar {
            shellToolbar
        }
    }

    // MARK: - Compact Adaptive Layout
    private var compactLayout: some View {
        NavigationStack {
            detailStage
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarLeading) {
                        Button {
                            showingCompactSetup = true
                        } label: {
                            Label("Setup", systemImage: "slider.horizontal.3")
                        }
                    }
                    shellToolbar
                }
                .sheet(isPresented: $showingCompactSetup) {
                    NavigationStack {
                        SetupView(model: model)
                            .toolbar {
                                ToolbarItem(placement: .confirmationAction) {
                                    Button("Done") {
                                        showingCompactSetup = false
                                    }
                                }
                            }
                    }
                }
        }
    }

    // MARK: - Main Detail Stage
    private var detailStage: some View {
        VStack(spacing: 0) {
            StudioHeaderView(model: model)

            ZStack(alignment: .bottom) {
                // Main Content (Viewfinder or Results)
                Group {
                    if model.activeView == .results && model.hasResult {
                        ResultsView(state: model.jobState) {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                model.activeView = .workspace
                            }
                        }
                    } else {
                        ViewfinderView(model: model)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                // Live Telemetry overlay docked at bottom when active or processing
                if model.jobState.status.isActive || model.jobState.status == .completed || model.jobState.status == .failed {
                    TelemetryPanel(
                        state: model.jobState,
                        onCancel: {
                            model.cancelJob()
                        }
                    )
                    .padding(.horizontal, 16)
                    .padding(.bottom, 12)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
        }
        .background(Color.psWorkspaceBg)
    }

    // MARK: - Toolbar Commands & Keyboard Shortcuts
    @ToolbarContentBuilder
    private var shellToolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            // Open Folder Shortcut
            Button {
                showingFolderPicker = true
            } label: {
                Label("Open Folder", systemImage: "folder")
            }
            .keyboardShortcut("o", modifiers: .command)

            // Start Job Shortcut (⌘R)
            Button {
                if !model.isProcessing {
                    model.startJob()
                }
            } label: {
                Label("Start Alignment", systemImage: "play.fill")
            }
            .disabled(model.isProcessing || !model.isReady || model.validationError != nil)
            .keyboardShortcut("r", modifiers: .command)

            // Cancel Job Shortcut (⌘.)
            Button {
                if model.isProcessing {
                    model.cancelJob()
                }
            } label: {
                Label("Cancel Alignment", systemImage: "stop.fill")
            }
            .disabled(!model.isProcessing)
            .keyboardShortcut(".", modifiers: .command)
        }
    }
}
