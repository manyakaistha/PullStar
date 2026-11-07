import SwiftUI
import AVKit
import Photos
import PullStarKit

public struct ResultsView: View {
    public let state: JobState
    public var onDismiss: (() -> Void)? = nil

    @StateObject private var photoSaver = PhotoSaver.shared
    @State private var selectedMedia: ResultMediaType = .image
    @State private var comparisonSplit: CGFloat = 0.5
    @State private var isComparing: Bool = true
    @State private var imageScale: CGFloat = 1.0
    @State private var imageOffset: CGSize = .zero
    @State private var toastMessage: String?
    @State private var isExportingDocument = false

    // Loaded UIImages
    @State private var resultImage: UIImage?
    @State private var referenceImage: UIImage?
    @State private var player: AVPlayer?

    public enum ResultMediaType: String, CaseIterable, Identifiable {
        case image = "Aligned Stack"
        case video = "Trail Video"
        public var id: String { rawValue }
    }

    public init(state: JobState, onDismiss: (() -> Void)? = nil) {
        self.state = state
        self.onDismiss = onDismiss
    }

    private var hasVideo: Bool {
        state.videoURL != nil
    }

    public var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Background deep void
                Color(red: 0.03, green: 0.03, blue: 0.04)
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    // 1. Result Header
                    headerBar

                    // 2. Main Media Stage (Comparison viewer or Video Player)
                    ZStack {
                        if selectedMedia == .video, let videoURL = state.videoURL {
                            videoStage(url: videoURL)
                        } else {
                            comparisonStage(in: geometry.size)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()

                    // 3. Footer Bar with Details and Tactile Actions
                    footerBar
                }

                // Toast banner for save/copy confirmations
                if let toast = toastMessage ?? photoSaver.successMessage ?? photoSaver.errorMessage {
                    VStack {
                        Spacer()
                        HStack(spacing: 8) {
                            Image(systemName: photoSaver.errorMessage != nil ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                                .foregroundColor(photoSaver.errorMessage != nil ? Color(red: 0.94, green: 0.44, blue: 0.44) : Color(red: 0.20, green: 0.83, blue: 0.60))
                            Text(toast)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundColor(.white)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(.ultraThinMaterial)
                        .clipShape(Capsule())
                        .overlay(
                            Capsule().stroke(Color.white.opacity(0.15), lineWidth: 1)
                        )
                        .shadow(color: Color.black.opacity(0.5), radius: 12, x: 0, y: 4)
                        .padding(.bottom, 80)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                    .animation(.spring(response: 0.3), value: toast)
                }
            }
        }
        .task(id: state.resultURL) {
            loadResultMedia()
        }
        .onDisappear {
            player?.pause()
            player = nil
        }
    }

    // MARK: - Header
    private var headerBar: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 2) {
                Text("A CLEARER PICTURE")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                    .tracking(2)

                Text("Your night, aligned.")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(.white)
            }

            Spacer()

            // Completion badge
            HStack(spacing: 6) {
                Image(systemName: "checkmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(Color(red: 0.20, green: 0.83, blue: 0.60))
                Text(state.frameCount > 0 ? "\(state.frameCount) images exported" : "Trails complete")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(.white)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color(red: 0.20, green: 0.83, blue: 0.60).opacity(0.15))
            .clipShape(Capsule())
            .overlay(
                Capsule().stroke(Color(red: 0.20, green: 0.83, blue: 0.60).opacity(0.4), lineWidth: 1)
            )

            // Image vs Video Selector
            if hasVideo {
                Picker("Media Type", selection: $selectedMedia) {
                    ForEach(ResultMediaType.allCases) { type in
                        Text(type.rawValue).tag(type)
                    }
                }
                .pickerStyle(.segmented)
                .frame(width: 220)
                .padding(.leading, 12)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(Color(red: 0.05, green: 0.05, blue: 0.06).opacity(0.9))
        .overlay(
            Rectangle().frame(height: 1).foregroundColor(Color.white.opacity(0.08)),
            alignment: .bottom
        )
    }

    // MARK: - Image / Comparison Stage
    private func comparisonStage(in size: CGSize) -> some View {
        GeometryReader { geo in
            ZStack {
                if let resultImage {
                    // Result Image (Full / Zoomable)
                    Image(uiImage: resultImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: geo.size.width, height: geo.size.height)
                        .scaleEffect(imageScale)
                        .offset(imageOffset)

                    // Before image overlaid and masked with split slider
                    if let referenceImage, isComparing {
                        Image(uiImage: referenceImage)
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(width: geo.size.width, height: geo.size.height)
                            .scaleEffect(imageScale)
                            .offset(imageOffset)
                            .mask(
                                GeometryReader { maskGeo in
                                    Rectangle()
                                        .frame(width: max(0, maskGeo.size.width * comparisonSplit))
                                }
                            )

                        // Divider Line
                        Rectangle()
                            .fill(Color.white.opacity(0.85))
                            .frame(width: 2)
                            .position(x: geo.size.width * comparisonSplit, y: geo.size.height / 2)
                            .shadow(color: Color.black.opacity(0.5), radius: 4, x: 0, y: 0)

                        // Draggable Slider Handle
                        Circle()
                            .fill(.ultraThinMaterial)
                            .frame(width: 36, height: 36)
                            .overlay(
                                Image(systemName: "arrow.left.and.right")
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundColor(.white)
                            )
                            .overlay(
                                Circle().stroke(Color.white.opacity(0.6), lineWidth: 1.5)
                            )
                            .shadow(color: Color.black.opacity(0.4), radius: 6, x: 0, y: 2)
                            .position(x: geo.size.width * comparisonSplit, y: geo.size.height / 2)
                            .gesture(
                                DragGesture()
                                    .onChanged { val in
                                        let newSplit = min(max(0.02, val.location.x / geo.size.width), 0.98)
                                        comparisonSplit = newSplit
                                    }
                            )

                        // Before/After Badges
                        HStack {
                            Text("Original")
                                .font(.system(size: 11, weight: .bold, design: .monospaced))
                                .foregroundColor(.white)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Color.black.opacity(0.65))
                                .clipShape(RoundedRectangle(cornerRadius: 4))
                                .padding(16)

                            Spacer()

                            Text("Aligned stack")
                                .font(.system(size: 11, weight: .bold, design: .monospaced))
                                .foregroundColor(Color(red: 0.22, green: 0.74, blue: 0.97))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Color.black.opacity(0.65))
                                .clipShape(RoundedRectangle(cornerRadius: 4))
                                .padding(16)
                        }
                        .frame(maxHeight: .infinity, alignment: .top)
                    }
                } else {
                    ProgressView("Loading final stack…")
                        .tint(.white)
                        .foregroundColor(Color(white: 0.7))
                }
            }
            .contentShape(Rectangle())
            .gesture(
                MagnificationGesture()
                    .onChanged { val in
                        imageScale = max(0.5, min(10.0, val))
                    }
            )
            .onTapGesture(count: 2) {
                withAnimation(.easeInOut(duration: 0.25)) {
                    if imageScale > 1.2 {
                        imageScale = 1.0
                        imageOffset = .zero
                    } else {
                        imageScale = 2.5
                    }
                }
            }
        }
    }

    // MARK: - Video Player Stage
    private func videoStage(url: URL) -> some View {
        Group {
            if let player {
                VideoPlayer(player: player)
                    .onAppear {
                        player.play()
                    }
            } else {
                ProgressView("Preparing video…")
                    .tint(.white)
                    .onAppear {
                        setupPlayer(with: url)
                    }
            }
        }
    }

    // MARK: - Footer
    private var footerBar: some View {
        HStack(alignment: .center, spacing: 16) {
            // Path and Frame Info
            VStack(alignment: .leading, spacing: 4) {
                if let resultURL = state.resultURL {
                    HStack(spacing: 4) {
                        Text("Saved to:")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Color(white: 0.5))
                        Text(resultURL.lastPathComponent)
                            .font(.system(size: 11, weight: .medium, design: .monospaced))
                            .foregroundColor(Color(white: 0.85))
                            .lineLimit(1)
                    }
                }

                if let framesDir = state.framesDirectory {
                    HStack(spacing: 4) {
                        Text("Aligned images:")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Color(white: 0.5))
                        Text(framesDir.lastPathComponent)
                            .font(.system(size: 11, weight: .medium, design: .monospaced))
                            .foregroundColor(Color(white: 0.7))
                            .lineLimit(1)
                    }
                }
            }

            Spacer()

            // Tactile Actions: Share, Save to Photos, Open in Files, Copy Path
            HStack(spacing: 10) {
                // Share Action
                if let url = selectedURL {
                    ShareLink(item: url) {
                        HStack(spacing: 6) {
                            Image(systemName: "square.and.arrow.up")
                                .font(.system(size: 12, weight: .semibold))
                            Text("Share")
                                .font(.system(size: 12, weight: .semibold))
                        }
                        .foregroundColor(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(Color(white: 0.14))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }

                // Save to Photos
                Button {
                    Task {
                        if selectedMedia == .video, let videoURL = state.videoURL {
                            await photoSaver.saveVideo(at: videoURL)
                        } else if let img = resultImage {
                            await photoSaver.saveImage(img)
                        }
                        showToast("Saved to Photos")
                    }
                } label: {
                    HStack(spacing: 6) {
                        if photoSaver.isSaving {
                            ProgressView().scaleEffect(0.6).tint(.white)
                        } else {
                            Image(systemName: "photo.badge.arrow.down")
                                .font(.system(size: 12, weight: .semibold))
                        }
                        Text("Save to Photos")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(Color(white: 0.14))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)

                // Open in Files / Reveal
                if let url = selectedURL {
                    Button {
                        UIPasteboard.general.string = url.path
                        showToast("Path copied: \(url.lastPathComponent)")
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "doc.on.doc")
                                .font(.system(size: 12, weight: .semibold))
                            Text("Copy Path")
                                .font(.system(size: 12, weight: .semibold))
                        }
                        .foregroundColor(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(Color(white: 0.14))
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .background(Color(red: 0.05, green: 0.05, blue: 0.06).opacity(0.95))
        .overlay(
            Rectangle().frame(height: 1).foregroundColor(Color.white.opacity(0.08)),
            alignment: .top
        )
    }

    private var selectedURL: URL? {
        selectedMedia == .video ? state.videoURL : state.resultURL
    }

    private func showToast(_ message: String) {
        toastMessage = message
        Task {
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            if toastMessage == message {
                toastMessage = nil
                photoSaver.dismissNotice()
            }
        }
    }

    private func loadResultMedia() {
        if let resultURL = state.resultURL {
            if let img = UIImage(contentsOfFile: resultURL.path) {
                self.resultImage = img
            }
        }
        if let refURL = state.detection?.referenceImage {
            if let refImg = UIImage(contentsOfFile: refURL.path) {
                self.referenceImage = refImg
            }
        }
        if let videoURL = state.videoURL {
            setupPlayer(with: videoURL)
        }
    }

    private func setupPlayer(with url: URL) {
        let playerItem = AVPlayerItem(url: url)
        let player = AVPlayer(playerItem: playerItem)
        player.actionAtItemEnd = .none

        NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: playerItem,
            queue: .main
        ) { _ in
            player.seek(to: .zero)
            player.play()
        }

        self.player = player
    }
}

// MARK: - Previews

#if DEBUG
#Preview("Results Completed") {
    var state = JobState()
    state.status = .completed
    state.stage = .done
    state.frameCount = 142
    state.resultURL = URL(fileURLWithPath: "/tmp/aligned_output.tif")
    state.framesDirectory = URL(fileURLWithPath: "/tmp/aligned_frames")

    return ResultsView(state: state)
}
#endif
