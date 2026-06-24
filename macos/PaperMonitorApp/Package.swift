// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PaperMonitorApp",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "PaperMonitorCore", targets: ["PaperMonitorCore"]),
        .executable(name: "PaperMonitorApp", targets: ["PaperMonitorApp"]),
    ],
    targets: [
        .target(
            name: "PaperMonitorCore",
            path: "Sources/PaperMonitorCore"
        ),
        .executableTarget(
            name: "PaperMonitorApp",
            dependencies: ["PaperMonitorCore"],
            path: "Sources/PaperMonitorApp"
        ),
        .testTarget(
            name: "PaperMonitorAppUnitTests",
            dependencies: ["PaperMonitorCore"],
            path: "Tests/PaperMonitorAppUnitTests"
        ),
    ]
)
