// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "PullStarKit",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [
        .library(name: "PullStarKit", targets: ["PullStarKit"]),
        .executable(name: "pullstar-cli", targets: ["pullstar-cli"]),
    ],
    targets: [
        .target(
            name: "PullStarKit",
            swiftSettings: [
                // The engine is per-pixel numeric Swift: unoptimised it runs ~40x slower
                // (24 x 12 MP frames: 275 s vs 6.7 s). Always optimise it, even in Debug app builds.
                .unsafeFlags(["-O"], .when(configuration: .debug)),
            ]
        ),
        .executableTarget(name: "pullstar-cli", dependencies: ["PullStarKit"]),
        .testTarget(name: "PullStarKitTests", dependencies: ["PullStarKit"]),
    ]
)
