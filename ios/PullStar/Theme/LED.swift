import SwiftUI

public enum LEDColor: String, Sendable, CaseIterable {
    case cyan
    case amber
    case emerald
    case danger
    case off

    public var tintColor: Color {
        switch self {
        case .cyan: return Color(hex: 0x8ec9d1)
        case .amber: return Color(hex: 0xceb791)
        case .emerald: return Color(hex: 0xa4cbb9)
        case .danger: return Color(hex: 0xefa7a7)
        case .off: return Color(white: 0.3)
        }
    }

    public var glowColor: Color {
        switch self {
        case .cyan: return Color(hex: 0x8ec9d1, alpha: 0.5)
        case .amber: return Color(hex: 0xceb791, alpha: 0.4)
        case .emerald: return Color(hex: 0xa4cbb9, alpha: 0.5)
        case .danger: return Color(hex: 0xefa7a7, alpha: 0.5)
        case .off: return Color.clear
        }
    }
}

public struct LEDIndicator: View {
    public let color: LEDColor
    public let label: String?
    public let size: CGFloat

    public init(color: LEDColor, label: String? = nil, size: CGFloat = 6) {
        self.color = color
        self.label = label
        self.size = size
    }

    public var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color.tintColor)
                .frame(width: size, height: size)
                .shadow(color: color.glowColor, radius: color == .off ? 0 : 4, x: 0, y: 0)
            if let label {
                Text(label)
                    .font(.psStatus)
                    .foregroundColor(.psTextSecondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label ?? "Status: \(color.rawValue)")
    }
}
