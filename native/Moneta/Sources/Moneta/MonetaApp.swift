import SwiftUI

@main
struct MonetaApp: App {
    @StateObject private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup("Moneta") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 1080, minHeight: 720)
                .task { await model.start() }
                .onChange(of: scenePhase) { _, phase in
                    guard phase == .active else { return }
                    Task { await model.refresh(includeSecondary: true, passive: true) }
                }
        }
        .defaultSize(width: 1440, height: 920)
        .windowToolbarStyle(.unifiedCompact)

        Settings {
            VStack(alignment: .leading, spacing: 12) {
                Text("Moneta").font(.title2.bold())
                Text("Uses the private finance service on this Mac at 127.0.0.1:8765. No credentials or ledger data are stored inside the app.")
                    .foregroundStyle(.secondary)
                    .frame(width: 420, alignment: .leading)
            }
            .padding(24)
        }
    }
}
