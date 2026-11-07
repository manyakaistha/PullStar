// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "PullStarKit",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [.library(name: "PullStarKit", targets: ["PullStarKit"])],
    targets: [
        .target(name: "PullStarKit"),
        .testTarget(name: "PullStarKitTests", dependencies: ["PullStarKit"]),
    ]
)
