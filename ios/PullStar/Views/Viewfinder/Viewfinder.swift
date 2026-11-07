import SwiftUI
import PullStarKit

/// Port of frontend/src/components/CelestialViewfinder.tsx.
struct Viewfinder: View {
    @Bindable var model: AppModel
    var onChooseFolder: () -> Void

    enum Mode { case polaris, refStar }

    @State private var mode: Mode = .polaris
    @State private var image: UIImage?
    @State private var liveImage: UIImage?
    @State private var imageError: String?
    @State private var placementError: String?
    // Viewport: `scale` = screen points per source pixel, `offset` = top-left of the image in view space.
    @State private var scale: CGFloat = 1
    @State private var offset: CGPoint = .zero
    @State private var viewport: CGSize = .zero
    @State private var didFitForKey: String?

    private var frame: SequenceInfo? {
        model.sequence.indices.contains(model.selectedReferenceIndex) ? model.sequence[model.selectedReferenceIndex] : nil
    }
    private var showingLivePreview: Bool { model.isProcessing && liveImage != nil }
    private var sourceSize: CGSize {
        if let frame, frame.width > 0, frame.height > 0 { return CGSize(width: frame.width, height: frame.height) }
        if let image { return CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale) }
        return CGSize(width: 1, height: 1)
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            canvasStage
            referenceGuide
            if let message = placementError ?? model.detectionError {
                Text(message).font(PS.note).foregroundStyle(PS.danger)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 8)
            } else if let notice = model.detectionNotice {
                Text(notice).font(PS.note).foregroundStyle(PS.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 8)
            }
            FilmstripView(model: model)
        }
        .glassSurface()
        .task(id: frame?.url) { await loadImage() }
        .task(id: model.jobState.livePreviewRevision) { await loadLivePreview() }
        .onChange(of: model.isProcessing) { _, running in if !running { liveImage = nil } }
    }

    // MARK: Toolbar

    private var toolbar: some View {
        HStack(spacing: 8) {
            HStack(spacing: 4) {
                modeButton(.polaris, title: "Polaris", dot: PS.polaris, activeText: PS.polarisText)
                modeButton(.refStar, title: "Ref Star", dot: PS.refStar, activeText: PS.refStarText)
                Rectangle().fill(Color.white.opacity(0.1)).frame(width: 1, height: 18).padding(.horizontal, 2)
                Button { fit() } label: { Label("Reset", systemImage: "arrow.counterclockwise") }
                    .buttonStyle(TactileButtonStyle(kind: .toolbar(active: false), height: 38))
                    .accessibilityHint("Reset pan and zoom")
                Button { zoom(by: 1 / 1.25) } label: { Image(systemName: "minus") }
                    .buttonStyle(TactileButtonStyle(kind: .quiet, height: 38))
                    .accessibilityLabel("Zoom out")
                    .keyboardShortcut("-", modifiers: .command)
                Button { zoom(by: 1.25) } label: { Image(systemName: "plus") }
                    .buttonStyle(TactileButtonStyle(kind: .quiet, height: 38))
                    .accessibilityLabel("Zoom in")
                    .keyboardShortcut("=", modifiers: .command)
                Text("\(Int((scale * 100).rounded()))%")
                    .font(PS.mono).foregroundStyle(Color(hex: 0xd4d4d8))
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.black.opacity(0.3)))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.white.opacity(0.08)))
                    .padding(.trailing, 4)
            }
            .disabled(image == nil)
            .padding(4)
            .background(Capsule().fill(LinearGradient(colors: [Color.white.opacity(0.047), Color.white.opacity(0.008)], startPoint: .topLeading, endPoint: .bottomTrailing)))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.094)))

            Spacer(minLength: 8)

            HStack(spacing: 6) {
                Button {
                    model.isDetecting ? model.cancelDetection() : model.detectStars()
                } label: {
                    if model.isDetecting { Label("Cancel detection", systemImage: "stop.fill") }
                    else { Label("Detect references", systemImage: "sparkles") }
                }
                .buttonStyle(TactileButtonStyle(kind: model.isDetecting ? .cancel : .toolbar(active: false), height: 38))
                .disabled(!model.isDetecting && (model.isProcessing || model.sequence.isEmpty))
                if let confidence = model.detectionConfidence {
                    Text(String(format: "%.1f%%", confidence * 100)).font(PS.mono).foregroundStyle(Color(hex: 0xe4e4e7))
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.black.opacity(0.3)))
                        .padding(.trailing, 4)
                }
            }
            .padding(4)
            .background(Capsule().fill(LinearGradient(colors: [Color.white.opacity(0.047), Color.white.opacity(0.008)], startPoint: .topLeading, endPoint: .bottomTrailing)))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.094)))
        }
        .padding(10)
        .background(LinearGradient(colors: [Color.white.opacity(0.016), .clear], startPoint: .top, endPoint: .bottom))
        .overlay(alignment: .bottom) { Rectangle().fill(Color.white.opacity(0.04)).frame(height: 1) }
    }

    private func modeButton(_ value: Mode, title: String, dot: Color, activeText: Color) -> some View {
        Button { mode = value } label: {
            HStack(spacing: 8) {
                Circle().fill(dot).frame(width: 8, height: 8)
                Text(title).foregroundStyle(mode == value ? activeText : Color(hex: 0xc8c8cf))
            }
        }
        .buttonStyle(TactileButtonStyle(kind: .toolbar(active: mode == value), height: 38))
        .accessibilityAddTraits(mode == value ? .isSelected : [])
    }

    // MARK: Canvas

    private var canvasStage: some View {
        GeometryReader { geo in
            ZStack {
                PS.workspace
                CanvasGrid().stroke(Color.white.opacity(0.035), lineWidth: 1)
                if let live = liveImage, showingLivePreview {
                    Image(uiImage: live).resizable().interpolation(.high).aspectRatio(contentMode: .fit)
                        .padding(8)
                        .transition(.opacity)
                } else if let image {
                    ReferenceCanvas(image: image, sourceSize: sourceSize, scale: $scale, offset: $offset,
                                    polaris: model.config.polaris, secondStar: model.config.secondStar,
                                    detectedStars: model.detectedStars,
                                    mode: mode,
                                    interactionEnabled: !model.isProcessing && !model.isDetecting,
                                    onPlace: place)
                }
                if showingLivePreview {
                    HStack(spacing: 8) {
                        Circle().fill(PS.driftX).frame(width: 7, height: 7).shadow(color: PS.driftX, radius: 5)
                        Text("Live trails · building from aligned frames")
                    }
                    .font(PS.caption).foregroundStyle(Color(hex: 0xb6dfe2))
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Capsule().fill(Color(hex: 0x071012, alpha: 0.85)))
                    .overlay(Capsule().strokeBorder(PS.driftX.opacity(0.33)))
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .padding(14)
                    .accessibilityAddTraits(.updatesFrequently)
                }
                if image == nil && model.sequence.isEmpty { EmptyViewfinder(onChooseFolder: onChooseFolder) }
                if let imageError, !model.sequence.isEmpty {
                    Text(imageError).font(PS.body).foregroundStyle(PS.danger).padding(30)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .clipped()
            .onAppear { viewport = geo.size; fitIfNeeded(force: true) }
            .onChange(of: geo.size) { _, size in viewport = size; fitIfNeeded(force: true) }
        }
        .frame(minHeight: 280)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(showingLivePreview
                            ? "Live aligned star trail preview. Reference selection is paused while alignment runs."
                            : "Reference star image. Tap to place the selected reference. Pinch to zoom, drag to pan.")
    }

    private var guideText: String {
        if !model.detectedStars.isEmpty { return "\(model.detectedStars.count) stars matched. Automatic alignment preserves trails without Polaris." }
        if model.config.polaris != nil {
            return model.config.secondStar != nil
                ? "Both references selected. Your sequence is ready to align."
                : "Polaris selected. Add a reference star for rotation correction."
        }
        return image != nil ? "Stars are matched automatically when you start. Polaris is optional." : "Load frames to start selecting references."
    }

    private var referenceGuide: some View {
        HStack(spacing: 10) {
            Image(systemName: "scope").font(.system(size: 14))
            Text(guideText).lineLimit(2)
            Spacer(minLength: 12)
            if viewport.width > 640 {
                Text("Pinch to zoom · Drag to pan").font(.system(size: 11)).foregroundStyle(Color(hex: 0x8e8e96))
            }
        }
        .font(PS.caption).foregroundStyle(Color(hex: 0xa1a1aa))
        .padding(.horizontal, 16).padding(.vertical, 10)
        .overlay(alignment: .top) { Rectangle().fill(Color.white.opacity(0.047)).frame(height: 1) }
    }

    // MARK: Actions

    private func place(_ point: CGPoint) {
        guard model.selectedReferenceIndex == 0 else {
            placementError = "Select the first frame before placing manual reference stars."
            return
        }
        placementError = nil
        model.clearDetection()
        switch mode {
        case .polaris: model.config.polaris = point
        case .refStar: model.config.secondStar = point
        }
        UISelectionFeedbackGenerator().selectionChanged()
    }

    private func fit() {
        guard viewport.width > 0, image != nil else { return }
        let s = min(viewport.width / sourceSize.width, viewport.height / sourceSize.height) * 0.94
        withAnimation(.snappy(duration: 0.25)) {
            scale = s
            offset = CGPoint(x: (viewport.width - sourceSize.width * s) / 2, y: (viewport.height - sourceSize.height * s) / 2)
        }
    }

    private func fitIfNeeded(force: Bool = false) {
        let key = "\(frame?.url.path ?? "")|\(Int(viewport.width))x\(Int(viewport.height))"
        if force || didFitForKey != key { didFitForKey = key; fit() }
    }

    private func zoom(by factor: CGFloat) {
        let center = CGPoint(x: viewport.width / 2, y: viewport.height / 2)
        let newScale = min(max(scale * factor, 0.01), 40)
        withAnimation(.snappy(duration: 0.2)) {
            offset = CGPoint(x: center.x - (center.x - offset.x) * newScale / scale,
                             y: center.y - (center.y - offset.y) * newScale / scale)
            scale = newScale
        }
    }

    private func loadImage() async {
        imageError = nil
        placementError = nil
        guard let frame else { image = nil; return }
        if let cached = await ImageCache.shared.image(for: frame.url, maxDimension: 2048) {
            image = cached; fit(); return
        }
        do {
            let data = try await model.loadPreview(for: frame.url, maxDimension: 2048)
            guard let loaded = UIImage(data: data) else { throw CocoaError(.fileReadCorruptFile) }
            await ImageCache.shared.insert(loaded, for: frame.url, maxDimension: 2048)
            image = loaded
            fit()
        } catch {
            image = nil
            imageError = "This frame could not be previewed."
        }
    }

    private func loadLivePreview() async {
        guard model.isProcessing, let url = model.jobState.livePreviewURL else { return }
        let loaded = await Task.detached { UIImage(contentsOfFile: url.path) }.value
        if let loaded { withAnimation(.easeInOut(duration: 0.25)) { liveImage = loaded } }
    }
}

// MARK: - Interactive reference canvas

private struct ReferenceCanvas: View {
    let image: UIImage
    let sourceSize: CGSize
    @Binding var scale: CGFloat
    @Binding var offset: CGPoint
    let polaris: CGPoint?
    let secondStar: CGPoint?
    let detectedStars: [CGPoint]
    let mode: Viewfinder.Mode
    let interactionEnabled: Bool
    let onPlace: (CGPoint) -> Void

    private enum DragKind { case undecided, pan, reticle(Viewfinder.Mode) }
    @State private var dragKind: DragKind = .undecided
    @State private var dragStartOffset: CGPoint = .zero
    @State private var pinchBase: (scale: CGFloat, offset: CGPoint)?
    @State private var pinchedDuringTouch = false
    @State private var loupe: (point: CGPoint, screen: CGPoint, mode: Viewfinder.Mode)?

    private func toScreen(_ p: CGPoint) -> CGPoint { CGPoint(x: offset.x + p.x * scale, y: offset.y + p.y * scale) }
    private func toSource(_ p: CGPoint) -> CGPoint { CGPoint(x: (p.x - offset.x) / scale, y: (p.y - offset.y) / scale) }
    private func inside(_ p: CGPoint) -> Bool { p.x >= 0 && p.y >= 0 && p.x < sourceSize.width && p.y < sourceSize.height }

    var body: some View {
        ZStack(alignment: .topLeading) {
            Image(uiImage: image).resizable().interpolation(.high)
                .frame(width: sourceSize.width * scale, height: sourceSize.height * scale)
                .offset(x: offset.x, y: offset.y)
            Canvas { ctx, _ in drawOverlays(&ctx) }
                .allowsHitTesting(false)
            if let loupe {
                Loupe(image: image, sourceSize: sourceSize, point: loupe.point, color: loupe.mode == .polaris ? PS.polaris : PS.refStar)
                    .position(x: loupe.screen.x, y: max(80, loupe.screen.y - 110))
                    .allowsHitTesting(false)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .contentShape(Rectangle())
        .gesture(dragGesture.simultaneously(with: pinchGesture))
    }

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if pinchBase != nil { return }
                switch dragKind {
                case .undecided:
                    dragStartOffset = offset
                    if interactionEnabled, let hit = reticleHit(at: value.startLocation) {
                        dragKind = .reticle(hit)
                    } else if hypot(value.translation.width, value.translation.height) > 6 {
                        dragKind = .pan
                    }
                case .pan:
                    offset = CGPoint(x: dragStartOffset.x + value.translation.width, y: dragStartOffset.y + value.translation.height)
                case .reticle(let which):
                    let p = toSource(value.location)
                    guard inside(p) else { return }
                    // Only the active mode's reticle is hit-tested, so `which == mode`.
                    loupe = (p, value.location, which)
                    onPlace(p)
                }
            }
            .onEnded { value in
                defer { dragKind = .undecided; loupe = nil; pinchedDuringTouch = false }
                if case .undecided = dragKind, !pinchedDuringTouch, interactionEnabled {
                    let p = toSource(value.location)
                    if inside(p) { onPlace(p) }
                }
            }
    }

    private var pinchGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                if pinchBase == nil { pinchBase = (scale, offset); pinchedDuringTouch = true; dragKind = .undecided }
                guard let base = pinchBase else { return }
                let newScale = min(max(base.scale * value.magnification, 0.01), 40)
                let anchor = value.startLocation
                scale = newScale
                offset = CGPoint(x: anchor.x - (anchor.x - base.offset.x) * newScale / base.scale,
                                 y: anchor.y - (anchor.y - base.offset.y) * newScale / base.scale)
            }
            .onEnded { _ in pinchBase = nil }
    }

    private func reticleHit(at location: CGPoint) -> Viewfinder.Mode? {
        let target = mode == .polaris ? polaris : secondStar
        if let target, hypot(toScreen(target).x - location.x, toScreen(target).y - location.y) < 30 { return mode }
        return nil
    }

    private func drawOverlays(_ ctx: inout GraphicsContext) {
        for star in detectedStars {
            let c = toScreen(star)
            ctx.stroke(Path(ellipseIn: CGRect(x: c.x - 9, y: c.y - 9, width: 18, height: 18)), with: .color(PS.success.opacity(0.85)), lineWidth: 1.2)
        }
        if let a = polaris, let b = secondStar {
            var line = Path(); line.move(to: toScreen(a)); line.addLine(to: toScreen(b))
            ctx.stroke(line, with: .color(.white.opacity(0.35)), style: StrokeStyle(lineWidth: 1, dash: [4, 5]))
        }
        if let p = polaris { drawReticle(&ctx, at: toScreen(p), color: PS.polaris, label: "POLARIS") }
        if let p = secondStar { drawReticle(&ctx, at: toScreen(p), color: PS.refStar, label: "REF STAR") }
    }

    private func drawReticle(_ ctx: inout GraphicsContext, at c: CGPoint, color: Color, label: String) {
        let r: CGFloat = 14
        ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: r * 2, height: r * 2)), with: .color(color), lineWidth: 1.5)
        var cross = Path()
        for (dx, dy) in [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)] {
            cross.move(to: CGPoint(x: c.x + dx * 5, y: c.y + dy * 5))
            cross.addLine(to: CGPoint(x: c.x + dx * 22, y: c.y + dy * 22))
        }
        ctx.stroke(cross, with: .color(color.opacity(0.9)), lineWidth: 1)
        ctx.draw(Text(label).font(.system(size: 10, weight: .semibold)).foregroundStyle(color), at: CGPoint(x: c.x + 26, y: c.y - 22), anchor: .leading)
    }
}

/// Magnifier shown while dragging a reference reticle with a finger or Pencil.
private struct Loupe: View {
    let image: UIImage
    let sourceSize: CGSize
    let point: CGPoint
    let color: Color
    private let size: CGFloat = 132
    private let zoom: CGFloat = 1.6   // points per source pixel inside the loupe

    var body: some View {
        ZStack {
            Image(uiImage: image).resizable().interpolation(.none)
                .frame(width: sourceSize.width * zoom, height: sourceSize.height * zoom)
                .offset(x: size / 2 - point.x * zoom, y: size / 2 - point.y * zoom)
                .frame(width: size, height: size, alignment: .topLeading)
            Circle().strokeBorder(color, lineWidth: 1).frame(width: 18, height: 18)
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().strokeBorder(Color.white.opacity(0.6), lineWidth: 1.5))
        .shadow(color: .black.opacity(0.6), radius: 10, y: 4)
        .overlay(alignment: .bottom) {
            Text("\(Int(point.x)), \(Int(point.y))").font(.system(size: 10, design: .monospaced))
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(Capsule().fill(.black.opacity(0.7))).offset(y: 14)
        }
    }
}

private struct CanvasGrid: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let step: CGFloat = 80
        var x: CGFloat = step
        while x < rect.width { p.move(to: CGPoint(x: x, y: 0)); p.addLine(to: CGPoint(x: x, y: rect.height)); x += step }
        var y: CGFloat = step
        while y < rect.height { p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: rect.width, y: y)); y += step }
        return p
    }
}

/// `.viewfinder-empty` — scales down to fit short canvases (iPad landscape, Split View).
private struct EmptyViewfinder: View {
    var onChooseFolder: () -> Void
    var body: some View {
        GeometryReader { geo in
            let h = geo.size.height
            let roomy = h >= 470
            let compact = h < 340
            VStack(spacing: 0) {
                BrandIcon(size: roomy ? 92 : compact ? 52 : 68).padding(.bottom, roomy ? 22 : 14)
                Eyebrow(text: "FROM FIRST FRAME TO FINAL STACK").padding(.bottom, roomy ? 14 : 10)
                VStack(spacing: 0) {
                    Text("A whole night.").foregroundStyle(PS.textPrimary)
                    Text("One clear picture.").foregroundStyle(Color(hex: 0x94949c))
                }
                .font(.system(size: roomy ? 46 : compact ? 28 : 36, weight: .regular)).tracking(roomy ? -1.8 : -1.2)
                .padding(.bottom, roomy ? 18 : 12)
                if !compact {
                    Text("Load your night-sky sequence, set your reference stars,\nand bring every frame into alignment.")
                        .font(.system(size: roomy ? 15 : 14)).foregroundStyle(Color(hex: 0xa0a0a9)).multilineTextAlignment(.center).lineSpacing(4)
                        .padding(.bottom, roomy ? 26 : 18)
                }
                Button(action: onChooseFolder) { Label("Choose image folder", systemImage: "folder") }
                    .buttonStyle(TactileButtonStyle(kind: .secondary, height: 48))
                    .keyboardShortcut("o", modifiers: .command)
                if roomy {
                    Text("JPEG · PNG · TIFF · HEIC · RAW").font(.system(size: 11)).tracking(1).foregroundStyle(Color(hex: 0x929299))
                        .padding(.top, 18)
                }
            }
            .padding(20)
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .background(RadialGradient(colors: [Color.white.opacity(0.016), .clear], center: UnitPoint(x: 0.5, y: 0.4), startRadius: 0, endRadius: 500))
    }
}
