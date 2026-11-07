import SwiftUI

public extension Color {
    init(hex: UInt32, alpha: Double = 1.0) {
        let r = Double((hex >> 16) & 0xff) / 255.0
        let g = Double((hex >> 8) & 0xff) / 255.0
        let b = Double(hex & 0xff) / 255.0
        self.init(.sRGB, red: r, green: g, blue: b, opacity: alpha)
    }

    // Web Palette: Dark theme tokens from index.css
    static let psWorkspaceBg = Color(hex: 0x050505)
    static let psSurfaceSolid = Color(hex: 0x161617)
    static let psSurfaceFooter = Color(hex: 0x141415)
    static let psSurfaceFooterStart = Color(hex: 0x19191b)
    
    // Text
    static let psTextPrimary = Color(hex: 0xf2f2f3)
    static let psTextSecondary = Color(hex: 0xbababe)
    static let psTextMuted = Color(hex: 0x929299)
    static let psTextDim = Color(hex: 0x62626a)

    // Accents & Lines
    static let psAccent = Color(hex: 0xd8e5e7)
    static let psAccentFill = Color(white: 1.0, opacity: 0.07)
    static let psAccentLine = Color(white: 1.0, opacity: 0.21)
    static let psGlassLine = Color(white: 1.0, opacity: 0.11)
    static let psGlassLineStrong = Color(white: 1.0, opacity: 0.18)

    // Semantic colors
    static let psSuccess = Color(hex: 0xa4cbb9)
    static let psWarning = Color(hex: 0xceb791)
    static let psDanger = Color(hex: 0xefa7a7)

    // Cancel action styling
    static let psCancelBg = Color(hex: 0x30241f)
    static let psCancelBorder = Color(hex: 0xa67c59)
    static let psCancelText = Color(hex: 0xffe1c4)

    // Form controls
    static let psFieldInputBg = Color(hex: 0x080809)
    static let psFieldWellBg = Color.black.opacity(0.35)
}

public enum PSTheme {
    public static let panelRadius: CGFloat = 24
    public static let buttonRadius: CGFloat = 12
    public static let pillRadius: CGFloat = 999
    public static let minHitTarget: CGFloat = 44
}
