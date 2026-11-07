import SwiftUI

public struct Panel<Content: View>: View {
    public let cornerRadius: CGFloat
    public let padding: CGFloat
    public let content: Content

    public init(
        cornerRadius: CGFloat = PSTheme.panelRadius,
        padding: CGFloat = 16,
        @ViewBuilder content: () -> Content
    ) {
        self.cornerRadius = cornerRadius
        self.padding = padding
        self.content = content()
    }

    public var body: some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            stops: [
                                .init(color: Color(hex: 0x1e1e20, alpha: 0.75), location: 0.0),
                                .init(color: Color(hex: 0x0d0d0e, alpha: 0.88), location: 0.5),
                                .init(color: Color(hex: 0x18181a, alpha: 0.75), location: 1.0)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .stroke(
                                LinearGradient(
                                    stops: [
                                        .init(color: Color(white: 1.0, opacity: 0.18), location: 0.0),
                                        .init(color: Color(white: 1.0, opacity: 0.06), location: 0.5),
                                        .init(color: Color(white: 1.0, opacity: 0.03), location: 1.0)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1
                            )
                    )
            )
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .shadow(color: Color.black.opacity(0.35), radius: 20, x: 0, y: 10)
    }
}

public struct FieldWell<Content: View>: View {
    public let content: Content

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    public var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color.psFieldWellBg)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .stroke(Color(white: 1.0, opacity: 0.08), lineWidth: 1)
                    )
            )
    }
}
