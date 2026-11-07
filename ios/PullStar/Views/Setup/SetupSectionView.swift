import SwiftUI

public struct SetupSectionView<Content: View>: View {
    public let number: String
    public let title: String
    public let description: String
    public let content: Content

    public init(
        number: String,
        title: String,
        description: String,
        @ViewBuilder content: () -> Content
    ) {
        self.number = number
        self.title = title
        self.description = description
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                Text(number)
                    .font(.psSectionNumber)
                    .foregroundColor(Color(hex: 0xbdbdc4))
                    .frame(width: 28, height: 28)
                    .background(
                        RoundedRectangle(cornerRadius: 9, style: .continuous)
                            .fill(LinearGradient(colors: [Color.white.opacity(0.1), Color.white.opacity(0.02)], startPoint: .topLeading, endPoint: .bottomTrailing))
                            .overlay(
                                RoundedRectangle(cornerRadius: 9, style: .continuous)
                                    .stroke(Color.white.opacity(0.16), lineWidth: 1)
                            )
                    )

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.psSectionTitle)
                        .foregroundColor(.psTextPrimary)
                    Text(description)
                        .font(.psSectionDesc)
                        .foregroundColor(.psTextMuted)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                content
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 22)
        .overlay(alignment: .bottom) {
            Divider().background(Color.white.opacity(0.08))
        }
    }
}
