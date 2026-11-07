import SwiftUI
import PullStarKit

/// Bottom filmstrip reel showing sequence frames, async cached thumbnails, and reference selection.
public struct FilmstripView: View {
    public let sequence: [SequenceInfo]
    @Binding public var selectedIndex: Int
    public let previewLoader: (URL, Int) async throws -> Data
    public var gapCount: Int = 0
    public var onSetReferenceFrame: ((Int) -> Void)?

    @Namespace private var animationNamespace

    public init(
        sequence: [SequenceInfo],
        selectedIndex: Binding<Int>,
        previewLoader: @escaping (URL, Int) async throws -> Data,
        gapCount: Int = 0,
        onSetReferenceFrame: ((Int) -> Void)? = nil
    ) {
        self.sequence = sequence
        self._selectedIndex = selectedIndex
        self.previewLoader = previewLoader
        self.gapCount = gapCount
        self.onSetReferenceFrame = onSetReferenceFrame
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Header stats
            HStack {
                HStack(spacing: 6) {
                    Circle()
                        .fill(sequence.isEmpty ? Color(white: 0.4) : Color(red: 0.20, green: 0.83, blue: 0.60))
                        .frame(width: 6, height: 6)
                    if sequence.isEmpty {
                        Text("YOUR FRAME SEQUENCE")
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundColor(Color(white: 0.6))
                    } else {
                        let gapsText = gapCount > 0 ? " · \(gapCount) GAPS" : ""
                        Text("\(sequence.count) FRAMES\(gapsText)")
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundColor(Color(white: 0.7))
                    }
                }

                Spacer()

                if !sequence.isEmpty {
                    Text("Frame \(min(sequence.count, max(1, selectedIndex + 1))) / \(sequence.count)")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundColor(Color(white: 0.6))
                } else {
                    Text("No frames loaded")
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundColor(Color(white: 0.5))
                }
            }
            .padding(.horizontal, 4)

            // Horizontal Reel
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(spacing: 8) {
                        if sequence.isEmpty {
                            ForEach(0..<10, id: \.self) { i in
                                PlaceholderCell(index: i)
                            }
                        } else {
                            ForEach(Array(sequence.enumerated()), id: \.element.id) { index, item in
                                FilmstripCell(
                                    item: item,
                                    index: index,
                                    isSelected: selectedIndex == index,
                                    previewLoader: previewLoader,
                                    onSelect: {
                                        selectedIndex = index
                                    },
                                    onSetAsReference: {
                                        onSetReferenceFrame?(index)
                                    }
                                )
                                .id(index)
                            }
                        }
                    }
                    .padding(.horizontal, 2)
                    .padding(.vertical, 4)
                }
                .onChange(of: selectedIndex) { _, newIndex in
                    withAnimation(.easeInOut(duration: 0.2)) {
                        proxy.scrollTo(newIndex, anchor: .center)
                    }
                }
            }
            .frame(height: 72)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            Color(red: 0.04, green: 0.04, blue: 0.04)
                .opacity(0.85)
        )
        .overlay(
            Rectangle()
                .frame(height: 1)
                .foregroundColor(Color.white.opacity(0.08)),
            alignment: .top
        )
    }
}

private struct FilmstripCell: View {
    let item: SequenceInfo
    let index: Int
    let isSelected: Bool
    let previewLoader: (URL, Int) async throws -> Data
    let onSelect: () -> Void
    let onSetAsReference: () -> Void

    @State private var thumbnail: UIImage?
    @State private var isLoading = false

    var body: some View {
        Button(action: onSelect) {
            ZStack(alignment: .bottomLeading) {
                // Background container
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color(red: 0.03, green: 0.03, blue: 0.03))

                if let thumbnail {
                    Image(uiImage: thumbnail)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: 68, height: 64)
                        .clipped()
                } else {
                    ProgressView()
                        .scaleEffect(0.6)
                        .tint(.white.opacity(0.4))
                        .frame(width: 68, height: 64)
                }

                // Frame index badge
                Text(String(format: "%04d", index + 1))
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundColor(.white.opacity(0.85))
                    .padding(.horizontal, 4)
                    .padding(.vertical, 1.5)
                    .background(Color.black.opacity(0.65))
                    .clipShape(RoundedRectangle(cornerRadius: 3))
                    .padding(3)
            }
            .frame(width: 68, height: 64)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(
                        isSelected ? Color(red: 0.22, green: 0.74, blue: 0.97) : Color.white.opacity(0.12),
                        lineWidth: isSelected ? 2 : 1
                    )
            )
            .shadow(
                color: isSelected ? Color(red: 0.22, green: 0.74, blue: 0.97).opacity(0.4) : Color.clear,
                radius: 6,
                x: 0,
                y: 0
            )
        }
        .buttonStyle(.plain)
        .contextMenu {
            Button {
                onSetAsReference()
            } label: {
                Label("Set as Reference Frame", systemImage: "star.circle")
            }

            Button {
                UIPasteboard.general.string = item.url.path
            } label: {
                Label("Copy Path", systemImage: "doc.on.doc")
            }
        }
        .task(id: item.url) {
            await loadThumbnail()
        }
    }

    private func loadThumbnail() async {
        if let cached = await ImageCache.shared.image(for: item.url, maxDimension: 256) {
            self.thumbnail = cached
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            let data = try await previewLoader(item.url, 256)
            if let img = UIImage(data: data) {
                await ImageCache.shared.insert(img, for: item.url, maxDimension: 256)
                self.thumbnail = img
            }
        } catch {
            // Preview fallback or empty
        }
    }
}

private struct PlaceholderCell: View {
    let index: Int

    var body: some View {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Color(red: 0.04, green: 0.04, blue: 0.04))
            .frame(width: 68, height: 64)
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(Color.white.opacity(0.06), lineWidth: 1)
            )
            .overlay(
                Text(String(format: "%04d", index))
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundColor(Color(white: 0.3))
            )
    }
}
