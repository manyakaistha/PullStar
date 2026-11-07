import Foundation
import PullStarKit

public enum EngineFactory {
    /// Factory creating the active PullStarEngine.
    /// Returns MockEngine during UI development until PullStarEngineImpl is linked.
    public static func make() -> any PullStarEngine {
        // SWAP LINE: Return PullStarEngineImpl() once linked
        return MockEngine()
    }
}
