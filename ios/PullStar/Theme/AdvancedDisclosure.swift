import SwiftUI

public struct AdvancedDisclosure<Content: View>: View {
    public let title: String
    public let content: Content
    @State private var isExpanded: Bool

    public init(
        _ title: String,
        isExpandedInitially: Bool = false,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self._isExpanded = State(initialValue: isExpandedInitially)
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider()
                .background(Color.white.opacity(0.08))
                .padding(.vertical, 4)

            Button(action: {
                withAnimation(.easeInOut(duration: 0.2)) {
                    isExpanded.toggle()
                }
            }) {
                HStack {
                    Text(title)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(isExpanded ? .psTextPrimary : .psTextMuted)
                    Spacer()
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.psTextMuted)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
                .frame(minHeight: PSTheme.minHitTarget)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(title)
            .accessibilityValue(isExpanded ? "Expanded" : "Collapsed")
            .accessibilityHint("Double tap to toggle additional settings")

            if isExpanded {
                VStack(alignment: .leading, spacing: 12) {
                    content
                }
                .padding(.vertical, 8)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}
