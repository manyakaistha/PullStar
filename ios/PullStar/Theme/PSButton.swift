import SwiftUI

public enum PSButtonVariant {
    case primary
    case secondary
    case pill
    case cancel
    case quiet
}

public struct PSButtonStyle: ButtonStyle {
    public let variant: PSButtonVariant
    public let isActive: Bool

    public init(variant: PSButtonVariant = .secondary, isActive: Bool = false) {
        self.variant = variant
        self.isActive = isActive
    }

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.psButton)
            .padding(.horizontal, variant == .pill ? 14 : 16)
            .frame(minHeight: PSTheme.minHitTarget)
            .background(background(isPressed: configuration.isPressed))
            .overlay(overlayBorder(isPressed: configuration.isPressed))
            .foregroundColor(foregroundColor)
            .clipShape(shape)
            .shadow(color: shadowColor(isPressed: configuration.isPressed), radius: configuration.isPressed ? 1 : 4, x: 0, y: configuration.isPressed ? 1 : 3)
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeOut(duration: 0.15), value: configuration.isPressed)
    }

    private var shape: some Shape {
        RoundedRectangle(cornerRadius: variant == .pill ? PSTheme.pillRadius : PSTheme.buttonRadius, style: .continuous)
    }

    @ViewBuilder
    private func background(isPressed: Bool) -> some View {
        switch variant {
        case .primary:
            LinearGradient(
                stops: [
                    .init(color: Color(hex: 0xf0f0f3), location: 0.0),
                    .init(color: Color(hex: 0xc9c9cf), location: 1.0)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        case .secondary:
            if isActive {
                LinearGradient(
                    colors: [Color(white: 1.0, opacity: 0.16), Color(white: 1.0, opacity: 0.08)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            } else {
                LinearGradient(
                    colors: [Color(white: 1.0, opacity: 0.08), Color(white: 1.0, opacity: 0.03)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
        case .pill:
            if isActive {
                LinearGradient(
                    colors: [Color(white: 1.0, opacity: 0.18), Color(white: 1.0, opacity: 0.08)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            } else {
                Color.clear
            }
        case .cancel:
            Color.psCancelBg
        case .quiet:
            if isPressed {
                Color.white.opacity(0.06)
            } else {
                Color.clear
            }
        }
    }

    @ViewBuilder
    private func overlayBorder(isPressed: Bool) -> some View {
        switch variant {
        case .primary:
            RoundedRectangle(cornerRadius: PSTheme.buttonRadius, style: .continuous)
                .stroke(Color.white.opacity(0.8), lineWidth: 1)
        case .secondary:
            RoundedRectangle(cornerRadius: PSTheme.buttonRadius, style: .continuous)
                .stroke(isActive ? Color.white.opacity(0.3) : Color.white.opacity(0.14), lineWidth: 1)
        case .pill:
            if isActive {
                Capsule()
                    .stroke(Color.white.opacity(0.24), lineWidth: 1)
            } else {
                EmptyView()
            }
        case .cancel:
            RoundedRectangle(cornerRadius: PSTheme.buttonRadius, style: .continuous)
                .stroke(Color.psCancelBorder, lineWidth: 1)
        case .quiet:
            EmptyView()
        }
    }

    private var foregroundColor: Color {
        switch variant {
        case .primary:
            return Color(hex: 0x171719)
        case .secondary:
            return isActive ? .psTextPrimary : .psTextSecondary
        case .pill:
            return isActive ? .psTextPrimary : .psTextMuted
        case .cancel:
            return .psCancelText
        case .quiet:
            return .psTextSecondary
        }
    }

    private func shadowColor(isPressed: Bool) -> Color {
        switch variant {
        case .primary:
            return Color.black.opacity(isPressed ? 0.2 : 0.4)
        case .secondary, .cancel:
            return Color.black.opacity(isPressed ? 0.1 : 0.25)
        case .pill, .quiet:
            return Color.clear
        }
    }
}

public struct PSButton: View {
    public let title: String
    public let iconName: String?
    public let systemImage: String?
    public let variant: PSButtonVariant
    public let isActive: Bool
    public let isLoading: Bool
    public let action: () -> Void

    public init(
        _ title: String,
        iconName: String? = nil,
        systemImage: String? = nil,
        variant: PSButtonVariant = .secondary,
        isActive: Bool = false,
        isLoading: Bool = false,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.iconName = iconName
        self.systemImage = systemImage
        self.variant = variant
        self.isActive = isActive
        self.isLoading = isLoading
        self.action = action
    }

    public var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if isLoading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: variant == .primary ? Color(hex: 0x171719) : .white))
                        .scaleEffect(0.8)
                } else if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 13, weight: .semibold))
                }
                Text(title)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(PSButtonStyle(variant: variant, isActive: isActive))
        .accessibilityLabel(title)
    }
}
