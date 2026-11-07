import SwiftUI
import PullStarKit

public enum ReferenceSelectionMode: String, CaseIterable, Sendable {
    case polaris = "Polaris"
    case secondStar = "Ref Star"
}

/// The interactive zoomable and pannable celestial canvas with reference reticles and magnifier.
public struct ViewfinderCanvas: View {
    public let image: UIImage?
    public let livePreviewImage: UIImage?
    public let showingLivePreview: Bool
    public let detectedStars: [CGPoint]
    @Binding public var polaris: CGPoint?
    @Binding public var secondStar: CGPoint?
    public var mode: ReferenceSelectionMode
    public var isProcessing: Bool
    public var onPlaceStar: ((CGPoint) -> Void)?

    @Binding public var scale: CGFloat
    @Binding public var offset: CGSize

    // Gesture tracking
    @GestureState private var gestureZoom: CGFloat = 1.0
    @GestureState private var gesturePan: CGSize = .zero

    // Dragging reticle state
    @State private var draggingTarget: ReferenceSelectionMode?
    @State private var activeLoupePoint: CGPoint?
    @State private var loupeScreenPosition: CGPoint = .zero

    public init(
        image: UIImage?,
        livePreviewImage: UIImage? = nil,
        showingLivePreview: Bool = false,
        detectedStars: [CGPoint] = [],
        polaris: Binding<CGPoint?>,
        secondStar: Binding<CGPoint?>,
        mode: ReferenceSelectionMode = .polaris,
        isProcessing: Bool = false,
        scale: Binding<CGFloat>,
        offset: Binding<CGSize>,
        onPlaceStar: ((CGPoint) -> Void)? = nil
    ) {
        self.image = image
        self.livePreviewImage = livePreviewImage
        self.showingLivePreview = showingLivePreview
        self.detectedStars = detectedStars
        self._polaris = polaris
        self._secondStar = secondStar
        self.mode = mode
        self.isProcessing = isProcessing
        self._scale = scale
        self._offset = offset
        self.onPlaceStar = onPlaceStar
    }

    private var currentImageToDisplay: UIImage? {
        showingLivePreview ? (livePreviewImage ?? image) : image
    }

    public var body: some View {
        GeometryReader { geometry in
            let viewSize = geometry.size

            ZStack {
                // Background deep void
                Color(red: 0.02, green: 0.02, blue: 0.02)
                    .ignoresSafeArea()

                // Subtle coordinate grid
                CoordinateGrid()
                    .stroke(Color.white.opacity(0.035), lineWidth: 1)

                // Background starfield if no image loaded
                if currentImageToDisplay == nil {
                    ProceduralStarfield()
                }

                // Celestial Image + Overlays Container
                ZStack {
                    if let displayImg = currentImageToDisplay {
                        Image(uiImage: displayImg)
                            .resizable()
                            .interpolation(.high)
                            .aspectRatio(contentMode: .fit)
                            .frame(width: displayImg.size.width, height: displayImg.size.height)
                            .overlay(
                                // Star markers and reticles in image coordinate space
                                ReticleOverlayLayer(
                                    imageSize: displayImg.size,
                                    scale: effectiveScale,
                                    detectedStars: detectedStars,
                                    polaris: polaris,
                                    secondStar: secondStar,
                                    showingLivePreview: showingLivePreview,
                                    draggingTarget: draggingTarget,
                                    onDragPolaris: { newPt, screenPos in
                                        handleDragReticle(mode: .polaris, point: newPt, screenPos: screenPos, imgSize: displayImg.size)
                                    },
                                    onDragSecondStar: { newPt, screenPos in
                                        handleDragReticle(mode: .secondStar, point: newPt, screenPos: screenPos, imgSize: displayImg.size)
                                    },
                                    onEndDrag: {
                                        draggingTarget = nil
                                        activeLoupePoint = nil
                                    }
                                )
                            )
                    }
                }
                .scaleEffect(effectiveScale)
                .offset(effectiveOffset)
                .contentShape(Rectangle())
                // Canvas gestures: Pan, Zoom, Tap to place, Double-tap to zoom
                .gesture(
                    makeSimultaneousGestures(in: viewSize, imgSize: currentImageToDisplay?.size ?? CGSize(width: 1, height: 1))
                )
                .onTapGesture(count: 2) { location in
                    handleDoubleTap(at: location, in: viewSize)
                }
                .onTapGesture { location in
                    handleTapToPlace(at: location, in: viewSize, imgSize: currentImageToDisplay?.size)
                }

                // Floating Magnifier Loupe when dragging a reticle
                if let activeLoupePoint, let draggingTarget, let img = currentImageToDisplay {
                    MagnifierLoupe(
                        image: img,
                        targetPoint: activeLoupePoint,
                        imageSize: img.size,
                        isPolaris: draggingTarget == .polaris
                    )
                    .position(
                        x: min(max(loupeScreenPosition.x, 80), viewSize.width - 80),
                        y: max(80, loupeScreenPosition.y - 110)
                    )
                    .transition(.scale.combined(with: .opacity))
                    .animation(.spring(response: 0.2, dampingFraction: 0.8), value: activeLoupePoint)
                }
            }
        }
    }

    private var effectiveScale: CGFloat {
        scale * gestureZoom
    }

    private var effectiveOffset: CGSize {
        CGSize(
            width: offset.width + gesturePan.width,
            height: offset.height + gesturePan.height
        )
    }

    private func makeSimultaneousGestures(in viewSize: CGSize, imgSize: CGSize) -> some Gesture {
        let zoom = MagnificationGesture()
            .updating($gestureZoom) { value, state, _ in
                state = value
            }
            .onEnded { value in
                let next = min(50.0, max(0.02, scale * value))
                scale = next
            }

        let pan = DragGesture(minimumDistance: 3)
            .updating($gesturePan) { value, state, _ in
                if draggingTarget == nil {
                    state = value.translation
                }
            }
            .onEnded { value in
                if draggingTarget == nil {
                    offset.width += value.translation.width
                    offset.height += value.translation.height
                }
            }

        return SimultaneousGesture(zoom, pan)
    }

    private func handleDoubleTap(at location: CGPoint, in viewSize: CGSize) {
        guard let img = currentImageToDisplay else { return }
        withAnimation(.easeInOut(duration: 0.25)) {
            if scale > 1.2 {
                // Reset to fit
                let fitScale = min(viewSize.width / img.size.width, viewSize.height / img.size.height) * 0.95
                scale = fitScale
                offset = .zero
            } else {
                // Zoom to 2.5x
                scale = 2.5
                // Center around tap location
                let dx = (viewSize.width / 2 - location.x) * 1.5
                let dy = (viewSize.height / 2 - location.y) * 1.5
                offset = CGSize(width: dx, height: dy)
            }
        }
    }

    private func handleTapToPlace(at screenPoint: CGPoint, in viewSize: CGSize, imgSize: CGSize?) {
        guard !isProcessing, !showingLivePreview, let imgSize else { return }
        
        // Convert screenPoint to image coordinates
        let center = CGPoint(x: viewSize.width / 2, y: viewSize.height / 2)
        let unscaledX = (screenPoint.x - center.x - offset.width) / scale
        let unscaledY = (screenPoint.y - center.y - offset.height) / scale

        let imageX = unscaledX + imgSize.width / 2
        let imageY = unscaledY + imgSize.height / 2

        guard imageX >= 0, imageX <= imgSize.width, imageY >= 0, imageY <= imgSize.height else {
            return
        }

        let finalPoint = CGPoint(x: imageX, y: imageY)
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()

        withAnimation(.spring(response: 0.25, dampingFraction: 0.75)) {
            if mode == .polaris {
                polaris = finalPoint
            } else {
                secondStar = finalPoint
            }
        }
        onPlaceStar?(finalPoint)
    }

    private func handleDragReticle(
        mode: ReferenceSelectionMode,
        point: CGPoint,
        screenPos: CGPoint,
        imgSize: CGSize
    ) {
        guard !isProcessing, !showingLivePreview else { return }
        let clamped = CGPoint(
            x: min(max(0, point.x), imgSize.width),
            y: min(max(0, point.y), imgSize.height)
        )
        draggingTarget = mode
        activeLoupePoint = clamped
        loupeScreenPosition = screenPos

        if mode == .polaris {
            polaris = clamped
        } else {
            secondStar = clamped
        }
    }
}

/// The overlay rendering Polaris, Ref Star 2, vector connecting line, and detected stars.
private struct ReticleOverlayLayer: View {
    let imageSize: CGSize
    let scale: CGFloat
    let detectedStars: [CGPoint]
    let polaris: CGPoint?
    let secondStar: CGPoint?
    let showingLivePreview: Bool
    let draggingTarget: ReferenceSelectionMode?

    let onDragPolaris: (CGPoint, CGPoint) -> Void
    let onDragSecondStar: (CGPoint, CGPoint) -> Void
    let onEndDrag: () -> Void

    var body: some View {
        Canvas { context, size in
            guard !showingLivePreview else { return }

            // 1. Detected Star Markers (Green)
            for (idx, star) in detectedStars.enumerated() {
                let rect = CGRect(
                    x: star.x - 7,
                    y: star.y - 7,
                    width: 14,
                    height: 14
                )
                context.stroke(
                    Path(ellipseIn: rect),
                    with: .color(Color(red: 0.20, green: 0.83, blue: 0.60)),
                    lineWidth: 1.2
                )

                // Crosshair tick marks
                var crosshair = Path()
                crosshair.move(to: CGPoint(x: star.x - 10, y: star.y))
                crosshair.addLine(to: CGPoint(x: star.x + 10, y: star.y))
                crosshair.move(to: CGPoint(x: star.x, y: star.y - 10))
                crosshair.addLine(to: CGPoint(x: star.x, y: star.y + 10))
                context.stroke(crosshair, with: .color(Color(red: 0.20, green: 0.83, blue: 0.60).opacity(0.7)), lineWidth: 1)

                // Label top 3 detected stars
                if idx < 3 {
                    let label = "STAR \(idx + 1)"
                    context.draw(
                        Text(label)
                            .font(.system(size: 10, weight: .bold, design: .monospaced))
                            .foregroundColor(Color(red: 0.20, green: 0.83, blue: 0.60)),
                        at: CGPoint(x: star.x + 24, y: star.y - 8)
                    )
                }
            }

            // 2. Connecting Vector Line between Polaris and Second Star
            if let p = polaris, let s = secondStar {
                var vectorPath = Path()
                vectorPath.move(to: p)
                vectorPath.addLine(to: s)
                context.stroke(
                    vectorPath,
                    with: .color(Color.white.opacity(0.65)),
                    style: StrokeStyle(lineWidth: 1.5, dash: [8, 6])
                )

                // Angle readout at midpoint
                let midPoint = CGPoint(x: (p.x + s.x) / 2, y: (p.y + s.y) / 2)
                let dx = s.x - p.x
                let dy = s.y - p.y
                let angle = (atan2(dy, dx) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
                let angleText = String(format: "%.2f°", angle)

                context.draw(
                    Text(angleText)
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(.white),
                    at: CGPoint(x: midPoint.x + 20, y: midPoint.y - 10)
                )
            }
        }
        .overlay(
            // Interactive Reticles (Polaris & Ref Star 2) with drag support
            ZStack {
                if !showingLivePreview {
                    if let polaris {
                        InteractiveReticle(
                            point: polaris,
                            label: "POLARIS",
                            color: Color(red: 0.22, green: 0.74, blue: 0.97),
                            scale: scale,
                            onDrag: onDragPolaris,
                            onEndDrag: onEndDrag
                        )
                    }

                    if let secondStar {
                        InteractiveReticle(
                            point: secondStar,
                            label: "REF STAR",
                            color: Color(red: 0.96, green: 0.62, blue: 0.04),
                            scale: scale,
                            onDrag: onDragSecondStar,
                            onEndDrag: onEndDrag
                        )
                    }
                }
            }
        )
    }
}

/// An individual draggable reticle for Polaris or Second Star.
private struct InteractiveReticle: View {
    let point: CGPoint
    let label: String
    let color: Color
    let scale: CGFloat
    let onDrag: (CGPoint, CGPoint) -> Void
    let onEndDrag: () -> Void

    @State private var dragOffset: CGSize = .zero

    var body: some View {
        let currentPos = CGPoint(x: point.x + dragOffset.width, y: point.y + dragOffset.height)

        ZStack(alignment: .topLeading) {
            // Target ring
            Circle()
                .stroke(color, lineWidth: 2)
                .frame(width: 32, height: 32)
                .position(currentPos)

            // Crosshair ticks
            Path { path in
                let r: CGFloat = 20
                let inner: CGFloat = 6
                path.move(to: CGPoint(x: currentPos.x - r, y: currentPos.y))
                path.addLine(to: CGPoint(x: currentPos.x - inner, y: currentPos.y))
                path.move(to: CGPoint(x: currentPos.x + inner, y: currentPos.y))
                path.addLine(to: CGPoint(x: currentPos.x + r, y: currentPos.y))

                path.move(to: CGPoint(x: currentPos.x, y: currentPos.y - r))
                path.addLine(to: CGPoint(x: currentPos.x, y: currentPos.y - inner))
                path.move(to: CGPoint(x: currentPos.x, y: currentPos.y + inner))
                path.addLine(to: CGPoint(x: currentPos.x, y: currentPos.y + r))
            }
            .stroke(color, lineWidth: 2)

            // Center pip
            Circle()
                .fill(color)
                .frame(width: 4, height: 4)
                .position(currentPos)

            // Label pill
            HStack(spacing: 4) {
                Text(String(format: "%@ [%.1f, %.1f]", label, currentPos.x, currentPos.y))
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(color)
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.black.opacity(0.75))
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .position(x: currentPos.x + 85, y: currentPos.y - 16)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Circle().size(width: 44, height: 44))
        .highPriorityGesture(
            DragGesture(minimumDistance: 1, coordinateSpace: .global)
                .onChanged { value in
                    let deltaX = value.translation.width / scale
                    let deltaY = value.translation.height / scale
                    let newPt = CGPoint(x: point.x + deltaX, y: point.y + deltaY)
                    onDrag(newPt, value.location)
                }
                .onEnded { _ in
                    onEndDrag()
                }
        )
    }
}

/// Subtle procedural coordinate grid background.
private struct CoordinateGrid: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let step: CGFloat = 80
        for x in stride(from: 0, to: rect.width, by: step) {
            path.move(to: CGPoint(x: x, y: 0))
            path.addLine(to: CGPoint(x: x, y: rect.height))
        }
        for y in stride(from: 0, to: rect.height, by: step) {
            path.move(to: CGPoint(x: 0, y: y))
            path.addLine(to: CGPoint(x: rect.width, y: y))
        }
        return path
    }
}

/// Subtle procedural starfield background for empty state.
private struct ProceduralStarfield: View {
    var body: some View {
        Canvas { context, size in
            let w = max(size.width, 1000)
            let h = max(size.height, 1000)
            for i in 0..<80 {
                let x = (sin(Double(i) * 123.0) * 1000.0 + 1000.0).truncatingRemainder(dividingBy: Double(w))
                let y = (cos(Double(i) * 321.0) * 1000.0 + 1000.0).truncatingRemainder(dividingBy: Double(h))
                let radius = Double(i % 3) * 0.8 + 0.6
                let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
                context.fill(Path(ellipseIn: rect), with: .color(Color.white.opacity(0.35)))
            }
        }
    }
}
