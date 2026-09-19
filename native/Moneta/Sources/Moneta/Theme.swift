import SwiftUI

enum MonetaTheme {
    static let forest = Color(red: 0.08, green: 0.24, blue: 0.18)
    static let amber = Color(red: 0.84, green: 0.55, blue: 0.20)
    static let teal = Color(red: 0.13, green: 0.48, blue: 0.40)
    static let coral = Color(red: 0.73, green: 0.29, blue: 0.25)
    static let ink = Color.primary
    static let muted = Color.secondary
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let canvas = Color(nsColor: .windowBackgroundColor)
    static let line = Color.primary.opacity(0.10)
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
