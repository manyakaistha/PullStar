import SwiftUI
import PullStarKit

@main
struct PullStarApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            StudioShellView(model: model)
                .preferredColorScheme(.dark)
        }
    }
}
