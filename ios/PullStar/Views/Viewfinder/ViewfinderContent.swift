import SwiftUI
import PullStarKit

/// Pure plain-input Viewfinder component mirroring the desktop CelestialViewfinder.
public struct ViewfinderContent: View {
    public let sequence: [SequenceInfo]
    @Binding public var selectedIndex: Int
    public let previewLoader: (URL, Int) async throws -> Data
    public let detectedStars: [CGPoint]
    @Binding public var polaris: CGPoint?
    @Binding public var secondStar: CGPoint?
    public var manualReferenceMode: Bool = true
    public var livePreviewURL: URL?
    public var isProcessing: Bool = false
    public var detectConfidence: Double? = nil
    public var isDetecting: Bool = false

    public var onBrowseFolder: (() -> Void)? = nil
    public var onAutoDetect: (() -> Void)? = nil
    public var onCancelDetect: (() -> Void)? = nil
    public var onSetReferenceFrame: ((Int) -> Void)? = nil

    // Canvas viewport state
    @State private var scale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var mode: ReferenceSelectionMode = .polaris

    // Image loading
    @State private var currentImage: UIImage?
    @State private var livePreviewImage: UIImage?
    @State private var isLoadingImage = false
    @State private var imageError: String?

    public init(
        sequence: [SequenceInfo],
        selectedIndex: Binding<Int>,
        previewLoader: @escaping (URL, Int) async throws -> Data,
        detectedStars: [CGPoint] = [],
        polaris: Binding<CGPoint?>,
        secondStar: Binding<CGPoint?>,
        manualReferenceMode: Bool = true,
        livePreviewURL: URL? = nil,
        isProcessing: Bool = false,
        detectConfidence: Double? = nil,
        isDetecting: Bool = false,
        onBrowseFolder: (() -> Void)? = nil,
        onAutoDetect: (() -> Void)? = nil,
        onCancelDetect: (() -> Void)? = nil,
        onSetReferenceFrame: ((Int) -> Void)? = nil
    ) {
        self.sequence = sequence
        self._selectedIndex = selectedIndex
        self.previewLoader = previewLoader
        self.detectedStars = detectedStars
        self._polaris = polaris
        self._secondStar = secondStar
        self.manualReferenceMode = manualReferenceMode
        self.livePreviewURL = livePreviewURL
        self.isProcessing = isProcessing
        self.detectConfidence = detectConfidence
        self.isDetecting = isDetecting
        self.onBrowseFolder = onBrowseFolder
        self.onAutoDetect = onAutoDetect
        self.onCancelDetect = onCancelDetect
        self.onSetReferenceFrame = onSetReferenceFrame
    }

    private var currentFrameInfo: SequenceInfo? {
        guard !sequence.isEmpty, selectedIndex >= 0, selectedIndex < sequence.count else { return nil }
        return sequence[selectedIndex]
    }

    private var showingLivePreview: Bool {
        isProcessing && livePreviewURL != nil && livePreviewImage != nil
    }

    public var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Background
                Color(red: 0.02, green: 0.02, blue: 0.02)
                    .ignoresSafeArea()

                // 1. Celestial Canvas
                ViewfinderCanvas(
                    image: currentImage,
                    livePreviewImage: livePreviewImage,
                    showingLivePreview: showingLivePreview,
                    detectedStars: detectedStars,
                    polaris: $polaris,
                    secondStar: $secondStar,
                    mode: mode,
                    isProcessing: isProcessing,
                    scale: $scale,
                    offset: $offset
                )

                // 2. Empty State when no sequence is loaded
                if sequence.isEmpty && currentImage == nil {
                    EmptySequenceView(onBrowseFolder: onBrowseFolder)
                        .transition(.opacity)
                }

                // 3. Top Floating Glass Toolbars
                VStack(spacing: 0) {
                    HStack(spacing: 8) {
                        // Left Capsule: Reticle mode + Zoom controls
                        HStack(spacing: 4) {
                            // Polaris Mode Button
                            Button {
                                mode = .polaris
                            } label: {
                                HStack(spacing: 6) {
                                    Circle()
                                        .fill(Color(red: 0.22, green: 0.74, blue: 0.97))
                                        .frame(width: 8, height: 8)
                                    Text("Polaris")
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundColor(mode == .polaris ? Color(red: 0.50, green: 0.85, blue: 1.0) : .white.opacity(0.8))
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(mode == .polaris ? Color.white.opacity(0.12) : Color.clear)
                                .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)

                            // Ref Star Mode Button
                            Button {
                                mode = .secondStar
                            } label: {
                                HStack(spacing: 6) {
                                    Circle()
                                        .fill(Color(red: 0.96, green: 0.62, blue: 0.04))
                                        .frame(width: 8, height: 8)
                                    Text("Ref Star")
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundColor(mode == .secondStar ? Color(red: 1.0, green: 0.78, blue: 0.3) : .white.opacity(0.8))
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(mode == .secondStar ? Color.white.opacity(0.12) : Color.clear)
                                .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)

                            Divider()
                                .frame(height: 16)
                                .background(Color.white.opacity(0.15))
                                .padding(.horizontal, 2)

                            // Reset Pan & Zoom
                            Button {
                                resetView(in: geometry.size)
                            } label: {
                                HStack(spacing: 4) {
                                    Image(systemName: "arrow.counterclockwise")
                                        .font(.system(size: 11, weight: .semibold))
                                    Text("Reset")
                                        .font(.system(size: 12, weight: .medium))
                                }
                                .foregroundColor(.white.opacity(0.85))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 6)
                            }
                            .buttonStyle(.plain)

                            // Fit Button
                            Button {
                                fitToScreen(in: geometry.size)
                            } label: {
                                Text("Fit")
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                    .foregroundColor(.white.opacity(0.8))
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 6)
                            }
                            .buttonStyle(.plain)

                            // 100% Button
                            Button {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    scale = 1.0
                                    offset = .zero
                                }
                            } label: {
                                Text("100%")
                                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                    .foregroundColor(.white.opacity(0.8))
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 6)
                            }
                            .buttonStyle(.plain)

                            // Zoom Out
                            Button {
                                withAnimation(.easeInOut(duration: 0.15)) {
                                    scale = max(0.05, scale / 1.25)
                                }
                            } label: {
                                Image(systemName: "minus")
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundColor(.white.opacity(0.85))
                                    .frame(width: 26, height: 26)
                            }
                            .buttonStyle(.plain)

                            // Zoom In
                            Button {
                                withAnimation(.easeInOut(duration: 0.15)) {
                                    scale = min(50.0, scale * 1.25)
                                }
                            } label: {
                                Image(systemName: "plus")
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundColor(.white.opacity(0.85))
                                    .frame(width: 26, height: 26)
                            }
                            .buttonStyle(.plain)

                            // Scale Percentage Pill
                            Text(String(format: "%.0f%%", scale * 100))
                                .font(.system(size: 11, weight: .medium, design: .monospaced))
                                .foregroundColor(Color(white: 0.85))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(Color.black.opacity(0.4))
                                .clipShape(Capsule())
                                .overlay(
                                    Capsule()
                                        .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
                                )
                        }
                        .padding(4)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(Color.white.opacity(0.12), lineWidth: 0.8)
                        )
                        .shadow(color: Color.black.opacity(0.4), radius: 8, x: 0, y: 4)

                        Spacer()

                        // Right Capsule: Detect References
                        HStack(spacing: 6) {
                            if isDetecting {
                                Button {
                                    onCancelDetect?()
                                } label: {
                                    HStack(spacing: 6) {
                                        Image(systemName: "stop.fill")
                                            .font(.system(size: 10, weight: .bold))
                                        Text("Cancel detection")
                                            .font(.system(size: 12, weight: .semibold))
                                    }
                                    .foregroundColor(Color(red: 0.94, green: 0.44, blue: 0.44))
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 6)
                                }
                                .buttonStyle(.plain)
                            } else {
                                Button {
                                    onAutoDetect?()
                                } label: {
                                    HStack(spacing: 6) {
                                        Image(systemName: "sparkles")
                                            .font(.system(size: 11, weight: .semibold))
                                            .foregroundColor(Color(red: 0.20, green: 0.83, blue: 0.60))
                                        Text("Detect references")
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundColor(.white)
                                    }
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 6)
                                }
                                .buttonStyle(.plain)
                                .disabled(sequence.isEmpty || isProcessing)
                                .opacity(sequence.isEmpty || isProcessing ? 0.5 : 1.0)
                            }

                            if let confidence = detectConfidence {
                                Text(String(format: "%.1f%%", confidence * 100))
                                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                                    .foregroundColor(Color(red: 0.20, green: 0.83, blue: 0.60))
                                    .padding(.horizontal, 7)
                                    .padding(.vertical, 3)
                                    .background(Color.black.opacity(0.4))
                                    .clipShape(Capsule())
                                    .overlay(
                                        Capsule()
                                            .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
                                    )
                            }
                        }
                        .padding(4)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(Color.white.opacity(0.12), lineWidth: 0.8)
                        )
                        .shadow(color: Color.black.opacity(0.4), radius: 8, x: 0, y: 4)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 12)

                    Spacer()

                    // Live preview crossfade badge
                    if showingLivePreview {
                        HStack(spacing: 6) {
                            Circle()
                                .fill(Color(red: 0.20, green: 0.83, blue: 0.60))
                                .frame(width: 8, height: 8)
                            Text("Live trails · building from aligned frames")
                                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                                .foregroundColor(.white)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule()
                                .stroke(Color(red: 0.20, green: 0.83, blue: 0.60).opacity(0.4), lineWidth: 1)
                        )
                        .padding(.bottom, 8)
                        .transition(.scale.combined(with: .opacity))
                    }

                    // EXIF / Frame Info Bar & Reference Guide
                    VStack(spacing: 6) {
                        HStack {
                            if let frame = currentFrameInfo, let img = currentImage {
                                HStack(spacing: 8) {
                                    Text("\(Int(img.size.width)) × \(Int(img.size.height))")
                                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                                        .foregroundColor(Color(white: 0.65))
                                    if frame.isRaw {
                                        Text("RAW")
                                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                                            .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                                            .padding(.horizontal, 4)
                                            .padding(.vertical, 1)
                                            .background(Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.15))
                                            .clipShape(RoundedRectangle(cornerRadius: 3))
                                    }
                                    Text(frame.name)
                                        .font(.system(size: 11, weight: .regular))
                                        .foregroundColor(Color(white: 0.5))
                                        .lineLimit(1)
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(Color.black.opacity(0.55))
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                            }

                            Spacer()

                            // Guide status pill
                            HStack(spacing: 6) {
                                Image(systemName: "scope")
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                                Text(guideText)
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundColor(.white.opacity(0.9))

                                Text("·")
                                    .foregroundColor(.white.opacity(0.4))
                                Text("Pinch to zoom · Drag to pan · Tap to place")
                                    .font(.system(size: 10, weight: .regular))
                                    .foregroundColor(.white.opacity(0.5))
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 4)
                            .background(.ultraThinMaterial)
                            .clipShape(Capsule())
                            .overlay(
                                Capsule()
                                    .stroke(Color.white.opacity(0.1), lineWidth: 0.5)
                            )
                        }
                        .padding(.horizontal, 14)

                        // Filmstrip Reel
                        FilmstripView(
                            sequence: sequence,
                            selectedIndex: $selectedIndex,
                            previewLoader: previewLoader,
                            onSetReferenceFrame: onSetReferenceFrame
                        )
                    }
                }
            }
            .task(id: selectedIndex) {
                await loadSelectedImage(in: geometry.size)
            }
            .task(id: livePreviewURL) {
                await loadLivePreview()
            }
            .onAppear {
                Task {
                    await loadSelectedImage(in: geometry.size)
                }
            }
        }
    }

    private var guideText: String {
        if !detectedStars.isEmpty {
            return "\(detectedStars.count) stars matched. Automatic alignment preserves trails without Polaris."
        } else if polaris != nil && secondStar != nil {
            return "Both references selected. Your sequence is ready to align."
        } else if polaris != nil {
            return "Polaris selected. Add a reference star for rotation correction."
        } else if currentImage != nil {
            return "Stars are matched automatically when you start. Polaris is optional."
        } else {
            return "Load frames to start selecting references."
        }
    }

    private func resetView(in viewSize: CGSize) {
        fitToScreen(in: viewSize)
    }

    private func fitToScreen(in viewSize: CGSize) {
        guard let img = currentImage else {
            scale = 1.0
            offset = .zero
            return
        }
        let availableHeight = max(100, viewSize.height - 180)
        let scaleX = (viewSize.width - 40) / img.size.width
        let scaleY = availableHeight / img.size.height
        let fitScale = min(scaleX, scaleY) * 0.92

        withAnimation(.easeInOut(duration: 0.25)) {
            scale = fitScale
            offset = CGSize(
                width: 0,
                height: -20
            )
        }
    }

    private func loadSelectedImage(in viewSize: CGSize) async {
        guard let frame = currentFrameInfo else {
            currentImage = nil
            return
        }

        if let cached = await ImageCache.shared.image(for: frame.url, maxDimension: 2048) {
            self.currentImage = cached
            if scale == 1.0 { fitToScreen(in: viewSize) }
            return
        }

        isLoadingImage = true
        defer { isLoadingImage = false }

        do {
            let data = try await previewLoader(frame.url, 2048)
            if let img = UIImage(data: data) {
                await ImageCache.shared.insert(img, for: frame.url, maxDimension: 2048)
                self.currentImage = img
                if scale == 1.0 { fitToScreen(in: viewSize) }
            }
        } catch {
            self.imageError = "This frame could not be previewed. Check the local image service or choose another frame."
        }
    }

    private func loadLivePreview() async {
        guard let livePreviewURL else {
            livePreviewImage = nil
            return
        }
        do {
            let data = try await previewLoader(livePreviewURL, 2048)
            if let img = UIImage(data: data) {
                withAnimation(.easeInOut(duration: 0.3)) {
                    self.livePreviewImage = img
                }
            }
        } catch {
            // Live preview failure is non-fatal
        }
    }
}

/// The empty state callout matching the web app.
private struct EmptySequenceView: View {
    var onBrowseFolder: (() -> Void)?

    var body: some View {
        VStack(spacing: 16) {
            // Stylized app icon / celestial symbol
            ZStack {
                Circle()
                    .fill(Color(white: 0.08))
                    .frame(width: 88, height: 88)
                Circle()
                    .stroke(Color.white.opacity(0.12), lineWidth: 1)
                    .frame(width: 88, height: 88)

                Image(systemName: "sparkles")
                    .font(.system(size: 38))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
            }
            .shadow(color: Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.25), radius: 20, x: 0, y: 0)

            Text("FROM FIRST FRAME TO FINAL STACK")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                .tracking(2)

            VStack(spacing: 4) {
                Text("A whole night.")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(.white)
                Text("One clear picture.")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundColor(Color(red: 0.55, green: 0.85, blue: 1.0))
            }

            Text("Load your night-sky sequence, set your reference stars,\nand bring every frame into alignment.")
                .font(.system(size: 14, weight: .regular))
                .foregroundColor(Color(white: 0.65))
                .multilineTextAlignment(.center)
                .lineSpacing(4)

            if let onBrowseFolder {
                Button(action: onBrowseFolder) {
                    HStack(spacing: 8) {
                        Image(systemName: "folder")
                            .font(.system(size: 14, weight: .semibold))
                        Text("Choose image folder")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    .foregroundColor(.black)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .shadow(color: Color.white.opacity(0.15), radius: 8, x: 0, y: 4)
                }
                .buttonStyle(.plain)
                .padding(.top, 4)
            }

            Text("JPEG · PNG · TIFF · RAW")
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundColor(Color(white: 0.4))
                .padding(.top, 8)
        }
        .padding(32)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(Color(red: 0.06, green: 0.06, blue: 0.07).opacity(0.75))
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )
        )
        .shadow(color: Color.black.opacity(0.5), radius: 30, x: 0, y: 12)
    }
}
