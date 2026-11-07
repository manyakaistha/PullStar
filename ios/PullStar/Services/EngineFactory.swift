import Foundation
import PullStarKit

enum EngineFactory {
    /// The real on-device engine. The simulated `MockEngine` is only used by the DEBUG
    /// snapshot harness (`PULLSTAR_SNAPSHOT`) or when `PULLSTAR_MOCK_ENGINE` is set.
    static func make() -> any PullStarEngine {
        #if DEBUG || PULLSTAR_HARNESS
        let env = ProcessInfo.processInfo.environment
        if env["PULLSTAR_MOCK_ENGINE"] != nil || (env["PULLSTAR_SNAPSHOT"] != nil && env["PULLSTAR_SNAPSHOT_INPUT"] == nil) {
            return MockEngine()
        }
        #endif
        return PullStarEngineImpl()
    }
}
