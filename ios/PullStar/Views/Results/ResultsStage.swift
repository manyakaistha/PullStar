import SwiftUI
import AVKit
import PullStarKit

/// Port of LiveTelemetry's `showcaseOnly` results view ("Your night, aligned.").
struct ResultsStage: View {
    @Bindable var model: AppModel
    @StateObject private var saver = PhotoSaver.shared
    @State private var result: UIImage?
    @State private var original: UIImage?
    @State private var split: CGFloat = 0.5
    @State private var showVideo = false
    @State private var imageError = false

    private var state: JobState { model.jobState }
    private var noStack: Bool { model.config.noStack }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading
            if showVideo, let video = state.videoURL {
                VideoPlayer(player: AVPlayer(url: video))
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Color.white.opacity(0.08)))
            } else {
                comparison
            }
            footer
        }
        .padding(26)
        .glassSurface()
        .task(id: state.resultURL) { await load() }
    }

    private var heading: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Eyebrow(text: "A CLEARER PICTURE")
                Text("Your night, aligned.").font(.system(size: 30)).tracking(-0.9).foregroundStyle(PS.textPrimary)
            }
            Spacer()
            if state.videoURL != nil {
                SegmentedControl(selection: $showVideo, options: [(false, "Image"), (true, "Video")]).frame(width: 200)
            }
            Label(noStack ? "\(state.frameCount) images exported" : "Trails complete", systemImage: "checkmark")
                .font(.system(size: 13)).foregroundStyle(PS.success)
        }
    }

    /// Rect the result occupies when fitted into `box` (both images are drawn into this same
    /// rect so the original and the aligned stack stay registered under the divider).
    private func imageRect(in box: CGSize) -> CGRect {
        guard let size = (result ?? original)?.size, size.width > 0, size.height > 0, box.width > 0, box.height > 0 else {
            return CGRect(origin: .zero, size: box)
        }
        let scale = min(box.width / size.width, box.height / size.height)
        let w = size.width * scale, h = size.height * scale
        return CGRect(x: (box.width - w) / 2, y: (box.height - h) / 2, width: w, height: h)
    }

    private var comparison: some View {
        GeometryReader { geo in
            let rect = imageRect(in: geo.size)
            let dividerX = rect.minX + rect.width * split
            ZStack(alignment: .topLeading) {
                PS.workspace
                if let result {
                    Image(uiImage: result).resizable().interpolation(.high)
                        .frame(width: rect.width, height: rect.height)
                        .offset(x: rect.minX, y: rect.minY)
                }
                if let original {
                    // Mask in the image rect's own coordinates: everything left of the divider shows the original.
                    Image(uiImage: original).resizable().interpolation(.high)
                        .frame(width: rect.width, height: rect.height)
                        .mask(alignment: .leading) {
                            Rectangle().frame(width: max(0, rect.width * split), height: rect.height)
                        }
                        .offset(x: rect.minX, y: rect.minY)
                    Rectangle().fill(Color(hex: 0xeeeeee)).frame(width: 1, height: rect.height)
                        .offset(x: dividerX - 0.5, y: rect.minY)
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: 0xa5a5aa), Color(hex: 0xf1f1f3), Color(hex: 0xa5a5aa)], startPoint: .leading, endPoint: .trailing))
                        .overlay(Capsule().strokeBorder(Color.white.opacity(0.56)))
                        .frame(width: 11, height: 46)
                        .shadow(color: .black.opacity(0.6), radius: 6, y: 2)
                        .offset(x: dividerX - 5.5, y: rect.midY - 23)
                        .accessibilityHidden(true)
                    tag("Original").offset(x: rect.minX + 14, y: rect.minY + 14)
                }
                tag(noStack ? "Aligned image" : "Aligned stack")
                    .frame(width: rect.width - 28, alignment: .trailing)
                    .offset(x: rect.minX + 14, y: rect.minY + 14)
                if imageError {
                    Text("Preview unavailable. Export the original output below.").font(PS.note).foregroundStyle(PS.danger)
                        .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(.black.opacity(0.8)))
                        .frame(width: geo.size.width, height: geo.size.height - 20, alignment: .bottom)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .topLeading)
            .contentShape(Rectangle())
            // Tap anywhere to move the divider; horizontal drags scrub it, vertical drags still scroll the page.
            .onTapGesture { location in moveDivider(to: location.x, in: rect) }
            .simultaneousGesture(DragGesture(minimumDistance: 6).onChanged { value in
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                moveDivider(to: value.location.x, in: rect)
            })
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Image comparison")
            .accessibilityValue("\(Int(split * 100)) percent original")
            .accessibilityAdjustableAction { direction in
                split = min(1, max(0, split + (direction == .increment ? 0.05 : -0.05)))
            }
        }
        .frame(minHeight: 320)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(Color.white.opacity(0.08)))
    }

    private func moveDivider(to x: CGFloat, in rect: CGRect) {
        guard original != nil, rect.width > 0 else { return }
        split = min(1, max(0, (x - rect.minX) / rect.width))
    }

    private func tag(_ text: String) -> some View {
        Text(text).font(.system(size: 11)).padding(.horizontal, 11).padding(.vertical, 6)
            .background(Capsule().fill(.black.opacity(0.6)))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.15)))
    }

    private var footer: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 20) { paths; Spacer(minLength: 12); actions }
            VStack(alignment: .leading, spacing: 16) { paths; actions }
        }
    }

    private var paths: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let url = state.resultURL { pathLine("Saved to", url) }
            if let frames = state.framesDirectory, !noStack { pathLine("Aligned images", frames) }
            if noStack { Text("Preview shows the first exported exposure. The sequence is ready for your editing app.").font(PS.caption).foregroundStyle(Color(hex: 0x888894)) }
            if let message = saver.successMessage ?? saver.errorMessage {
                Text(message).font(PS.caption).foregroundStyle(saver.errorMessage == nil ? PS.success : PS.danger)
            }
        }
        .frame(maxWidth: 420, alignment: .leading)
    }

    private func pathLine(_ label: String, _ url: URL) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(PS.caption).foregroundStyle(Color(hex: 0x888894))
            Text(url.lastPathComponent).font(.system(size: 13)).foregroundStyle(Color(hex: 0xb3b3bd)).lineLimit(1).truncationMode(.middle)
        }
    }

    private var actions: some View {
        HStack(spacing: 10) {
            if let url = state.resultURL, !noStack {
                Button { Task { await saver.saveImage(at: url) } } label: { Label("Save to Photos", systemImage: "photo.badge.plus") }
                    .buttonStyle(TactileButtonStyle(kind: .primary, height: 48))
                    .disabled(saver.isSaving)
                ShareLink(item: url) { Label("Share image", systemImage: "square.and.arrow.up") }
                    .buttonStyle(TactileButtonStyle(kind: .secondary, height: 48))
            }
            if let video = state.videoURL {
                Button { Task { await saver.saveVideo(at: video) } } label: { Label("Save video", systemImage: "film") }
                    .buttonStyle(TactileButtonStyle(kind: .secondary, height: 48))
                    .disabled(saver.isSaving)
            }
            if let frames = state.framesDirectory ?? (noStack ? state.resultURL : nil) {
                ShareLink(item: frames) { Label("Share aligned images", systemImage: "square.stack") }
                    .buttonStyle(TactileButtonStyle(kind: .secondary, height: 48))
            }
        }
    }

    private func load() async {
        imageError = false
        split = 0.5
        guard let url = state.resultURL else { result = nil; return }
        let previewTarget = noStack ? (try? FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: nil).sorted { $0.lastPathComponent < $1.lastPathComponent }.first(where: { !$0.hasDirectoryPath })) ?? url : url
        if let data = try? await model.loadPreview(for: previewTarget, maxDimension: 2048), let image = UIImage(data: data) {
            result = image
        } else {
            imageError = true
        }
        if let first = model.sequence.first, let data = try? await model.loadPreview(for: first.url, maxDimension: 2048) {
            original = UIImage(data: data)
        }
    }
}
