import SwiftUI
import PullStarKit

/// `.filmstrip` — the frame reel under the viewfinder.
struct FilmstripView: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                HStack(spacing: 7) {
                    Circle().fill(Color(hex: 0xa1a1aa)).frame(width: 6, height: 6)
                    Text(model.sequence.isEmpty
                         ? "YOUR FRAME SEQUENCE"
                         : "\(model.sequence.count) FRAMES" + (model.gapCount > 0 ? " · \(model.gapCount) GAP\(model.gapCount == 1 ? "" : "S")" : ""))
                }
                Spacer()
                Text(model.sequence.isEmpty ? "No frames loaded" : "Frame \(model.selectedReferenceIndex + 1) / \(model.sequence.count)")
            }
            .font(.system(size: 12, design: .monospaced))
            .foregroundStyle(Color(hex: 0xa1a1aa))
            .padding(.horizontal, 4)

            Group {
                if model.sequence.isEmpty {
                    ScrollView(.horizontal) {
                        HStack(spacing: 8) {
                            ForEach(0..<10, id: \.self) { i in
                                Text(String(format: "%04d", i)).font(.system(size: 11, design: .monospaced)).foregroundStyle(Color(hex: 0x52525b))
                                    .frame(width: 76, height: 52)
                                    .background(RoundedRectangle(cornerRadius: 9).fill(Color(hex: 0x0a0a0a)))
                                    .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Color.white.opacity(0.05)))
                            }
                        }
                        .padding(2)
                    }
                    .scrollDisabled(true)
                    .accessibilityHidden(true)
                } else {
                    FrameReel(model: model)
                }
            }
            .scrollIndicators(.hidden)
            .frame(height: 56)
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(Color.black.opacity(0.2))
        .overlay(alignment: .top) { Rectangle().fill(Color.white.opacity(0.047)).frame(height: 1) }
    }
}

private struct FrameReel: View {
    @Bindable var model: AppModel
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal) {
                LazyHStack(spacing: 8) {
                    ForEach(Array(model.sequence.enumerated()), id: \.element.id) { index, frame in
                        FilmstripThumb(frame: frame, selected: index == model.selectedReferenceIndex, model: model)
                            .id(index)
                            .onTapGesture { model.selectedReferenceIndex = index }
                            .accessibilityLabel("View frame \(index + 1), \(frame.name)")
                            .accessibilityAddTraits(index == model.selectedReferenceIndex ? [.isButton, .isSelected] : .isButton)
                    }
                }
                .padding(2)
            }
            .onChange(of: model.selectedReferenceIndex) { _, index in
                withAnimation { proxy.scrollTo(index, anchor: .center) }
            }
        }
    }
}

private struct FilmstripThumb: View {
    let frame: SequenceInfo
    let selected: Bool
    let model: AppModel
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Color(hex: 0x050505)
            if let image {
                Image(uiImage: image).resizable().aspectRatio(contentMode: .fill)
            } else {
                ProgressView().controlSize(.mini).tint(PS.textDim)
            }
        }
        .frame(width: 76, height: 52)
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous)
            .strokeBorder(selected ? Color(hex: 0xd4d4d8) : Color.white.opacity(0.1), lineWidth: selected ? 1.5 : 1))
        .shadow(color: selected ? .white.opacity(0.12) : .clear, radius: 4)
        .contentShape(Rectangle())
        .hoverEffect(.lift)
        .task(id: frame.url) {
            if let cached = await ImageCache.shared.image(for: frame.url, maxDimension: 256) { image = cached; return }
            if let data = try? await model.loadPreview(for: frame.url, maxDimension: 256), let loaded = UIImage(data: data) {
                await ImageCache.shared.insert(loaded, for: frame.url, maxDimension: 256)
                image = loaded
            }
        }
    }
}
