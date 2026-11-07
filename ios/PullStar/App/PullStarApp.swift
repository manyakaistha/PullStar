import SwiftUI
import PullStarKit

@main
struct PullStarApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            StudioView(model: model)
                .preferredColorScheme(.dark)
                #if DEBUG || PULLSTAR_HARNESS
                .task { await SnapshotHarness.runIfRequested(model) }
                #endif
        }
    }
}
