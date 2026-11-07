import SwiftUI

// MARK: - Tokens
//
// Mirrors frontend/src/index.css. Web pixel sizes are scaled ~1.2× for iPad viewing
// distance and touch, and every interactive element keeps a 44pt hit target.

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xff) / 255,
                  green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255,
                  opacity: alpha)
    }
}

enum PS {
    // Palette
    static let workspace = Color(hex: 0x050505)
    static let surface = Color(hex: 0x161617)
    static let textPrimary = Color(hex: 0xf2f2f3)
    static let textBody = Color(hex: 0xdcdce0)
    static let textSecondary = Color(hex: 0xbababe)
    static let textLabel = Color(hex: 0xaaaab2)
    static let textMuted = Color(hex: 0x96969e)
    static let textDim = Color(hex: 0x62626a)
    static let success = Color(hex: 0xa4cbb9)
    static let warning = Color(hex: 0xceb791)
    static let danger = Color(hex: 0xefa7a7)
    static let polaris = Color(hex: 0x38bdf8)      // tailwind sky-400
    static let polarisText = Color(hex: 0x7dd3fc)  // sky-300
    static let refStar = Color(hex: 0xfbbf24)      // amber-400
    static let refStarText = Color(hex: 0xfcd34d)  // amber-300
    static let driftX = Color(hex: 0x8ec9d1)
    static let driftY = Color(hex: 0xceb791)
    static let line = Color.white.opacity(0.055)   // #ffffff0e dividers
    static let hairline = Color.white.opacity(0.105)

    // Type scale
    static let eyebrow = Font.system(size: 10, weight: .semibold)
    static let caption = Font.system(size: 12)
    static let label = Font.system(size: 13)
    static let body = Font.system(size: 14)
    static let control = Font.system(size: 14, weight: .medium)
    static let note = Font.system(size: 12.5)
    static let mono = Font.system(size: 12, design: .monospaced)

    // Metrics
    static let panelRadius: CGFloat = 24
    static let fieldRadius: CGFloat = 12
    static let fieldHeight: CGFloat = 46
    static let setupWidth: CGFloat = 380
    static let gutter: CGFloat = 20
}

// MARK: - Glass surface (`.glass-surface`)

struct GlassSurface: ViewModifier {
    var radius: CGFloat = PS.panelRadius
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background {
                ZStack {
                    shape.fill(.ultraThinMaterial).opacity(0.35)
                    shape.fill(LinearGradient(
                        stops: [
                            .init(color: Color(hex: 0x1e1e20, alpha: 0.69), location: 0),
                            .init(color: Color(hex: 0x0d0d0e, alpha: 0.85), location: 0.5),
                            .init(color: Color(hex: 0x18181a, alpha: 0.69), location: 1),
                        ],
                        startPoint: .topLeading, endPoint: .bottomTrailing))
                    shape.fill(RadialGradient(colors: [Color.white.opacity(0.04), .clear],
                                              center: .topLeading, startRadius: 0, endRadius: 420))
                }
            }
            .clipShape(shape)
            .overlay {
                shape.strokeBorder(LinearGradient(colors: [Color.white.opacity(0.16), Color.white.opacity(0.07)],
                                                  startPoint: .top, endPoint: .bottom), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.5), radius: 20, y: 12)
    }
}

extension View {
    func glassSurface(radius: CGFloat = PS.panelRadius) -> some View { modifier(GlassSurface(radius: radius)) }

    /// `.field-input` inset well.
    func fieldWell(radius: CGFloat = PS.fieldRadius) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        return self
            .background(shape.fill(Color(hex: 0x080809)))
            .overlay(shape.strokeBorder(Color.white.opacity(0.086), lineWidth: 1))
            .overlay(alignment: .top) {
                shape.stroke(Color.black.opacity(0.55), lineWidth: 2).blur(radius: 2).clipShape(shape)
            }
    }
}

// MARK: - Buttons (`.tactile-button`, `.tactile-button-secondary`, `.action-cancel`)

struct TactileButtonStyle: ButtonStyle {
    enum Kind { case primary, secondary, cancel, toolbar(active: Bool), quiet }
    var kind: Kind = .secondary
    var height: CGFloat = PS.fieldHeight
    var fullWidth = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed
        configuration.label
            .font(PS.control)
            .lineLimit(1)
            .fixedSize(horizontal: !fullWidth, vertical: false)
            .padding(.horizontal, horizontalPadding)
            .frame(minHeight: height)
            .frame(maxWidth: fullWidth ? .infinity : nil)
            .foregroundStyle(foreground)
            .background(background)
            .overlay(border)
            .contentShape(Capsule())
            .shadow(color: .black.opacity(shadowOpacity), radius: 6, y: 3)
            .offset(y: pressed ? 1 : 0)
            .opacity(isEnabled ? 1 : 0.4)
            .animation(.easeOut(duration: 0.16), value: pressed)
            .hoverEffect(.highlight)
    }

    private var horizontalPadding: CGFloat {
        switch kind { case .toolbar, .quiet: 12; default: 18 }
    }
    private var radius: CGFloat {
        switch kind { case .toolbar, .quiet: height / 2; case .primary, .cancel: 14; default: PS.fieldRadius }
    }
    private var foreground: Color {
        switch kind {
        case .primary: Color(hex: 0x171719)
        case .cancel: Color(hex: 0xffe1c4)
        case .toolbar(let active): active ? PS.textPrimary : Color(hex: 0xc8c8cf)
        case .quiet: Color(hex: 0xc8c8cf)
        case .secondary: Color(hex: 0xd2d2d8)
        }
    }
    private var shadowOpacity: Double {
        switch kind { case .primary: 0.45; case .secondary: 0.3; case .toolbar(let a): a ? 0.3 : 0; default: 0 }
    }
    @ViewBuilder private var background: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        switch kind {
        case .primary:
            shape.fill(LinearGradient(colors: [Color(hex: 0xf0f0f3), Color(hex: 0xc9c9cf)], startPoint: .top, endPoint: .bottom))
        case .cancel:
            shape.fill(Color(hex: 0x30241f))
        case .secondary:
            shape.fill(LinearGradient(colors: [Color.white.opacity(0.075), Color.white.opacity(0.016)], startPoint: .top, endPoint: .bottom))
        case .toolbar(let active):
            shape.fill(active ? AnyShapeStyle(LinearGradient(colors: [Color.white.opacity(0.095), Color.white.opacity(0.03)], startPoint: .top, endPoint: .bottom)) : AnyShapeStyle(Color.clear))
        case .quiet:
            Color.clear
        }
    }
    @ViewBuilder private var border: some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        switch kind {
        case .primary: shape.strokeBorder(Color.white.opacity(0.75), lineWidth: 1)
        case .cancel: shape.strokeBorder(Color(hex: 0xa67c59), lineWidth: 1)
        case .secondary: shape.strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
        case .toolbar(let active): shape.strokeBorder(Color.white.opacity(active ? 0.125 : 0), lineWidth: 1)
        case .quiet: EmptyView()
        }
    }
}

extension ButtonStyle where Self == TactileButtonStyle {
    static var tactilePrimary: TactileButtonStyle { TactileButtonStyle(kind: .primary, height: 52, fullWidth: true) }
    static var tactileSecondary: TactileButtonStyle { TactileButtonStyle(kind: .secondary) }
}

// MARK: - Small pieces

struct StatusDot: View {
    var color: Color = PS.success
    var body: some View {
        Circle().fill(color).frame(width: 7, height: 7).shadow(color: color.opacity(0.4), radius: 4)
    }
}

struct Eyebrow: View {
    let text: String
    var body: some View {
        Text(text).font(PS.eyebrow).tracking(1.8).foregroundStyle(Color(hex: 0x929299))
    }
}

struct FieldLabel: View {
    let text: String
    var body: some View { Text(text).font(PS.label).foregroundStyle(PS.textLabel) }
}

struct HelperNote: View {
    let text: String
    var body: some View {
        Text(text).font(PS.note).foregroundStyle(Color(hex: 0xa1a1aa)).lineSpacing(2)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// `<select class="field-input">` — a menu styled as an inset field.
struct SelectField<Value: Hashable>: View {
    let title: String
    @Binding var selection: Value
    let options: [(Value, String)]

    var body: some View {
        Menu {
            Picker(title, selection: $selection) {
                ForEach(options, id: \.0) { option in Text(option.1).tag(option.0) }
            }
        } label: {
            HStack {
                Text(options.first(where: { $0.0 == selection })?.1 ?? "")
                    .font(PS.body).foregroundStyle(PS.textBody).lineLimit(1)
                Spacer(minLength: 8)
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(PS.textMuted)
            }
            .padding(.horizontal, 14)
            .frame(maxWidth: .infinity, minHeight: PS.fieldHeight)
            .fieldWell()
            .contentShape(Rectangle())
        }
        .accessibilityLabel(title)
    }
}

/// `<input class="field-input">`
struct InputField: View {
    let placeholder: String
    @Binding var text: String
    var onSubmit: () -> Void = {}
    var body: some View {
        TextField("", text: $text, prompt: Text(placeholder).foregroundStyle(Color(hex: 0x85858d)))
            .font(PS.body)
            .foregroundStyle(PS.textBody)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .submitLabel(.done)
            .onSubmit(onSubmit)
            .padding(.horizontal, 14)
            .frame(minHeight: PS.fieldHeight)
            .fieldWell()
    }
}

/// Read-only path display paired with a folder button (`.source-input-row`).
struct FolderField: View {
    let value: String?
    let placeholder: String
    let accessibilityTitle: String
    let action: () -> Void
    var body: some View {
        HStack(spacing: 8) {
            Button(action: action) {
                HStack {
                    Text(value ?? placeholder)
                        .font(PS.body)
                        .foregroundStyle(value == nil ? Color(hex: 0x85858d) : PS.textBody)
                        .lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14)
                .frame(maxWidth: .infinity, minHeight: PS.fieldHeight)
                .fieldWell()
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Button(action: action) {
                Image(systemName: "folder").font(.system(size: 17))
                    .frame(width: 22)
            }
            .buttonStyle(TactileButtonStyle(kind: .secondary))
            .accessibilityLabel(accessibilityTitle)
        }
    }
}

/// `.physical-switch` toggle row.
struct SettingToggle: View {
    let label: String
    var description: String?
    @Binding var isOn: Bool

    var body: some View {
        Toggle(isOn: $isOn) {
            VStack(alignment: .leading, spacing: 3) {
                Text(label).font(.system(size: 15, weight: .medium)).foregroundStyle(Color(hex: 0xe4e4e7))
                if let description {
                    Text(description).font(PS.note).foregroundStyle(Color(hex: 0xa1a1aa))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .toggleStyle(PhysicalSwitchStyle())
        .frame(minHeight: 48)
    }
}

struct PhysicalSwitchStyle: ToggleStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .center, spacing: 14) {
            configuration.label
            Spacer(minLength: 0)
            ZStack(alignment: configuration.isOn ? .trailing : .leading) {
                Capsule()
                    .fill(configuration.isOn
                          ? AnyShapeStyle(LinearGradient(colors: [Color(hex: 0x77777f), Color(hex: 0x515158)], startPoint: .top, endPoint: .bottom))
                          : AnyShapeStyle(Color(hex: 0x060607)))
                    .overlay(Capsule().strokeBorder(configuration.isOn ? Color(hex: 0xa3a3ad) : Color.white.opacity(0.13), lineWidth: 1))
                    .frame(width: 46, height: 27)
                Circle()
                    .fill(LinearGradient(colors: configuration.isOn ? [.white, Color(hex: 0xd1d1d9)] : [Color(hex: 0xa9a9b3), Color(hex: 0x686870)],
                                         startPoint: .top, endPoint: .bottom))
                    .frame(width: 19, height: 19)
                    .shadow(color: .black.opacity(0.55), radius: 2, y: 2)
                    .padding(.horizontal, 4)
            }
            .animation(.snappy(duration: 0.18), value: configuration.isOn)
        }
        .contentShape(Rectangle())
        .onTapGesture { configuration.isOn.toggle() }
        .opacity(isEnabled ? 1 : 0.5)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isToggle)
        .accessibilityValue(configuration.isOn ? "On" : "Off")
        .accessibilityAction { configuration.isOn.toggle() }
    }
}

/// `.physical-range` slider with value well.
struct SettingSlider: View {
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    var step: Double = 1
    var unit = ""
    var helper: String?

    private var display: String {
        step < 1 ? String(format: "%g", (value * 1000).rounded() / 1000) + unit : "\(Int(value.rounded()))\(unit)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label).font(.system(size: 15, weight: .medium)).foregroundStyle(Color(hex: 0xd4d4d8))
                Spacer()
                Text(display).font(PS.mono).foregroundStyle(Color(hex: 0xf4f4f5))
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(RoundedRectangle(cornerRadius: 7).fill(Color.black.opacity(0.3)))
                    .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(Color.white.opacity(0.07)))
            }
            Slider(value: $value, in: range, step: step)
                .tint(Color(hex: 0xccccd3))
                .frame(minHeight: 40)
                .accessibilityLabel(label)
                .accessibilityValue(display)
            if let helper { HelperNote(text: helper).padding(.top, -4) }
        }
    }
}

/// `.segmented-control`
struct SegmentedControl<Value: Hashable>: View {
    @Binding var selection: Value
    let options: [(Value, String)]
    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { option in
                let selected = option.0 == selection
                Button { selection = option.0 } label: {
                    Text(option.1).font(.system(size: 13, weight: selected ? .medium : .regular))
                        .frame(maxWidth: .infinity, minHeight: 36)
                        .foregroundStyle(selected ? Color(hex: 0xe9e9ed) : Color(hex: 0xa0a0a8))
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(selected ? Color.white.opacity(0.06) : .clear)
                                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .strokeBorder(Color.white.opacity(selected ? 0.14 : 0)))
                        )
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 11, style: .continuous).fill(Color.black.opacity(0.25)))
        .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous).strokeBorder(Color.white.opacity(0.08)))
    }
}

/// `<details class="setup-details">`
struct AdvancedDisclosure<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content
    @State private var isOpen = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(Color.white.opacity(0.043)).frame(height: 1)
            Button {
                withAnimation(.snappy(duration: 0.22)) { isOpen.toggle() }
            } label: {
                HStack {
                    Text(title).font(PS.label)
                        .foregroundStyle(isOpen ? Color(hex: 0xdddde2) : Color(hex: 0xa5a5ae))
                    Spacer()
                    Image(systemName: "chevron.down").font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(PS.textMuted)
                        .rotationEffect(.degrees(isOpen ? 180 : 0))
                }
                .frame(minHeight: 46)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityValue(isOpen ? "Expanded" : "Collapsed")
            if isOpen {
                VStack(alignment: .leading, spacing: 12) { content }
                    .padding(.top, 4).padding(.bottom, 12)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .clipped()
    }
}

struct BrandIcon: View {
    var size: CGFloat = 40
    var body: some View {
        Image("BrandLogo").resizable().interpolation(.high).aspectRatio(contentMode: .fit)
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: size * 0.225, style: .continuous))
            .accessibilityHidden(true)
    }
}
