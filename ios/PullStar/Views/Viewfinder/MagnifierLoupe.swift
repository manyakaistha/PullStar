import SwiftUI

/// A precision magnifying loupe shown when placing or dragging reference stars,
/// designed for Apple Pencil and touch interaction.
public struct MagnifierLoupe: View {
    public let image: UIImage?
    public let targetPoint: CGPoint          // In image coordinate space
    public let imageSize: CGSize             // Native image pixel dimensions
    public let isPolaris: Bool
    public let zoomFactor: CGFloat = 3.0
    public let loupeDiameter: CGFloat = 140

    public init(
        image: UIImage?,
        targetPoint: CGPoint,
        imageSize: CGSize,
        isPolaris: Bool
    ) {
        self.image = image
        self.targetPoint = targetPoint
        self.imageSize = imageSize
        self.isPolaris = isPolaris
    }

    private var accentColor: Color {
        isPolaris ? Color(red: 0.22, green: 0.74, blue: 0.97) : Color(red: 0.96, green: 0.62, blue: 0.04)
    }

    public var body: some View {
        VStack(spacing: 6) {
            ZStack {
                // Background dark disk
                Circle()
                    .fill(Color(red: 0.05, green: 0.05, blue: 0.05))

                // Magnified image portion
                if let image, imageSize.width > 0, imageSize.height > 0 {
                    GeometryReader { geo in
                        // Normalize targetPoint to 0...1
                        let u = targetPoint.x / imageSize.width
                        let v = targetPoint.y / imageSize.height
                        
                        let scaledWidth = imageSize.width * zoomFactor
                        let scaledHeight = imageSize.height * zoomFactor

                        Image(uiImage: image)
                            .resizable()
                            .interpolation(.none) // Crisp pixels when magnified
                            .frame(width: scaledWidth, height: scaledHeight)
                            .position(
                                x: geo.size.width / 2 - (u - 0.5) * scaledWidth,
                                y: geo.size.height / 2 - (v - 0.5) * scaledHeight
                            )
                    }
                    .clipShape(Circle())
                }

                // Precision grid inside loupe
                LoupeGrid()
                    .stroke(Color.white.opacity(0.12), lineWidth: 0.5)
                    .clipShape(Circle())

                // Reticle crosshair inside loupe
                ZStack {
                    // Outer guide ring
                    Circle()
                        .stroke(accentColor.opacity(0.8), lineWidth: 1.5)
                        .frame(width: 32, height: 32)

                    // Crosshair lines
                    Rectangle()
                        .fill(accentColor)
                        .frame(width: 1.5, height: 24)
                    Rectangle()
                        .fill(accentColor)
                        .frame(width: 24, height: 1.5)

                    // Center dot
                    Circle()
                        .fill(accentColor)
                        .frame(width: 3, height: 3)
                }

                // Loupe glass bezel & specular highlight
                Circle()
                    .strokeBorder(
                        LinearGradient(
                            colors: [Color.white.opacity(0.5), Color.white.opacity(0.1), Color.black.opacity(0.6)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 3
                    )
            }
            .frame(width: loupeDiameter, height: loupeDiameter)
            .shadow(color: Color.black.opacity(0.6), radius: 16, x: 0, y: 8)

            // Coordinate HUD Pill
            HStack(spacing: 4) {
                Circle()
                    .fill(accentColor)
                    .frame(width: 6, height: 6)
                Text(String(format: "%@ [%.1f, %.1f]", isPolaris ? "POLARIS" : "REF STAR", targetPoint.x, targetPoint.y))
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(.white)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(.ultraThinMaterial)
            .clipShape(Capsule())
            .overlay(
                Capsule()
                    .stroke(Color.white.opacity(0.2), lineWidth: 0.5)
            )
            .shadow(color: Color.black.opacity(0.4), radius: 4, x: 0, y: 2)
        }
    }
}

private struct LoupeGrid: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let step: CGFloat = 14
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
