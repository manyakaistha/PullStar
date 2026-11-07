import SwiftUI

public struct PSToggle: View {
    public let label: String
    @Binding public var isOn: Bool
    public let description: String?
    public let ledColor: LEDColor?
    public let disabled: Bool

    public init(
        _ label: String,
        isOn: Binding<Bool>,
        description: String? = nil,
        ledColor: LEDColor? = nil,
        disabled: Bool = false
    ) {
        self.label = label
        self._isOn = isOn
        self.description = description
        self.ledColor = ledColor
        self.disabled = disabled
    }

    public var body: some View {
        Button(action: {
            if !disabled {
                withAnimation(.easeInOut(duration: 0.18)) {
                    isOn.toggle()
                }
            }
        }) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        if let ledColor {
                            LEDIndicator(color: isOn ? ledColor : .off, size: 6)
                        }
                        Text(label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundColor(.psTextPrimary)
                    }
                    if let description {
                        Text(description)
                            .font(.system(size: 11, weight: .regular))
                            .foregroundColor(.psTextMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 8)

                // Physical switch element
                ZStack(alignment: isOn ? .trailing : .leading) {
                    RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .fill(
                            isOn
                                ? LinearGradient(colors: [Color(hex: 0x77777f), Color(hex: 0x515158)], startPoint: .top, endPoint: .bottom)
                                : LinearGradient(colors: [Color(hex: 0x060607), Color(hex: 0x060607)], startPoint: .top, endPoint: .bottom)
                        )
                        .frame(width: 36, height: 21)
                        .overlay(
                            RoundedRectangle(cornerRadius: 11, style: .continuous)
                                .stroke(isOn ? Color(hex: 0xa3a3ad) : Color.white.opacity(0.18), lineWidth: 1)
                        )

                    Circle()
                        .fill(
                            isOn
                                ? LinearGradient(colors: [Color.white, Color(hex: 0xd1d1d9)], startPoint: .top, endPoint: .bottom)
                                : LinearGradient(colors: [Color(hex: 0xa9a9b3), Color(hex: 0x686870)], startPoint: .top, endPoint: .bottom)
                        )
                        .frame(width: 15, height: 15)
                        .shadow(color: Color.black.opacity(0.4), radius: 2, x: 0, y: 1)
                        .padding(3)
                }
                .frame(width: 44, height: 44) // 44pt hit target area
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(disabled ? 0.45 : 1.0)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(label)
        .accessibilityValue(isOn ? "On" : "Off")
        .accessibilityHint(description ?? "")
    }
}
