import SwiftUI

enum MonetaTheme {
    // Semantic data colours need substantially more luminance on dark surfaces.
    // Keep the brand fill separate so prominent controls retain light text contrast.
    static let forest = adaptive(
        light: NSColor(srgbRed: 0.08, green: 0.24, blue: 0.18, alpha: 1),
        dark: NSColor(srgbRed: 0.44, green: 0.84, blue: 0.64, alpha: 1)
    )
    static let amber = adaptive(
        light: NSColor(srgbRed: 0.84, green: 0.55, blue: 0.20, alpha: 1),
        dark: NSColor(srgbRed: 0.97, green: 0.72, blue: 0.35, alpha: 1)
    )
    static let teal = adaptive(
        light: NSColor(srgbRed: 0.13, green: 0.48, blue: 0.40, alpha: 1),
        dark: NSColor(srgbRed: 0.32, green: 0.85, blue: 0.76, alpha: 1)
    )
    static let coral = adaptive(
        light: NSColor(srgbRed: 0.73, green: 0.29, blue: 0.25, alpha: 1),
        dark: NSColor(srgbRed: 1.00, green: 0.53, blue: 0.49, alpha: 1)
    )
    static let olive = adaptive(
        light: NSColor(srgbRed: 0.34, green: 0.48, blue: 0.35, alpha: 1),
        dark: NSColor(srgbRed: 0.60, green: 0.80, blue: 0.55, alpha: 1)
    )
    static let violet = adaptive(
        light: NSColor(srgbRed: 0.47, green: 0.40, blue: 0.58, alpha: 1),
        dark: NSColor(srgbRed: 0.78, green: 0.66, blue: 0.95, alpha: 1)
    )
    static let sky = adaptive(
        light: NSColor(srgbRed: 0.38, green: 0.55, blue: 0.62, alpha: 1),
        dark: NSColor(srgbRed: 0.52, green: 0.82, blue: 0.93, alpha: 1)
    )
    static let clay = adaptive(
        light: NSColor(srgbRed: 0.62, green: 0.46, blue: 0.34, alpha: 1),
        dark: NSColor(srgbRed: 0.88, green: 0.68, blue: 0.51, alpha: 1)
    )
    static let brandFill = Color(red: 0.08, green: 0.24, blue: 0.18)
    static let onBrand = Color(red: 0.96, green: 0.98, blue: 0.97)
    static let chartPalette: [Color] = [
        amber, forest, teal, coral, .blue, .purple, .cyan, .indigo,
        .pink, .mint, .brown, .orange, olive, violet, sky, clay,
    ]
    static let ink = Color.primary
    static let muted = Color.secondary
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let line = Color.primary.opacity(0.10)

    private static func adaptive(light: NSColor, dark: NSColor) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        })
    }
}

struct Panel<Content: View>: View {
    let title: String
    let subtitle: String?
    @ViewBuilder var content: Content

    init(_ title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                if let subtitle { Text(subtitle).font(.caption).foregroundStyle(.secondary) }
            }
            content
        }
        .padding(18)
        .background(MonetaTheme.panel, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(MonetaTheme.line))
    }
}

struct StatusPill: View {
    let text: String
    let isHealthy: Bool

    var body: some View {
        Label(text, systemImage: isHealthy ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
            .font(.caption.weight(.semibold))
            .foregroundStyle(isHealthy ? MonetaTheme.teal : MonetaTheme.coral)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background((isHealthy ? MonetaTheme.teal : MonetaTheme.coral).opacity(0.10), in: Capsule())
    }
}
