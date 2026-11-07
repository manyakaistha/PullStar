import SwiftUI

public struct PSSlider: View {
    public let label: String
    @Binding public var value: Double
    public let range: ClosedRange<Double>
    public let step: Double
    public let unit: String
    public let helperText: String?
    public let disabled: Bool

    public init(
        _ label: String,
        value: Binding<Double>,
        in range: ClosedRange<Double>,
        step: Double = 1.0,
        unit: String = "",
        helperText: String? = nil,
        disabled: Bool = false
    ) {
        self.label = label
        self._value = value
        self.range = range
        self.step = step
        self.unit = unit
        self.helperText = helperText
        self.disabled = disabled
    }

    private var formattedValue: String {
        if step < 0.1 {
            return String(format: "%.2f", value)
        } else if step < 1.0 {
            return String(format: "%.1f", value)
        } else {
            return "\(Int(value))"
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(label)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.psTextPrimary)
                Spacer()
                Text("\(formattedValue)\(unit)")
                    .font(.psValueReadout)
                    .foregroundColor(.psTextPrimary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Color.psFieldWellBg)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6, style: .continuous)
                                    .stroke(Color.white.opacity(0.1), lineWidth: 1)
                            )
                    )
            }

            Slider(
                value: Binding(
                    get: { self.value },
                    set: { newValue in
                        let stepped = (newValue / step).rounded() * step
                        self.value = min(max(stepped, range.lowerBound), range.upperBound)
                    }
                ),
                in: range
            )
            .tint(Color(hex: 0xccccd3))
            .frame(height: 32)
            .contentShape(Rectangle())

            if let helperText {
                Text(helperText)
                    .font(.system(size: 11, weight: .regular))
                    .foregroundColor(.psTextMuted)
            }
        }
        .frame(minHeight: 44)
        .opacity(disabled ? 0.45 : 1.0)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label)
        .accessibilityValue("\(formattedValue) \(unit)")
    }
}
