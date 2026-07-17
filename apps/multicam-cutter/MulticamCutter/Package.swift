// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MulticamCutter",
    platforms: [.macOS(.v14)],
    dependencies: [
        // Auto-Update-Framework (Appcast + EdDSA-signierte Releases)
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.6.0"),
    ],
    targets: [
        .executableTarget(
            name: "MulticamCutter",
            dependencies: [
                .product(name: "Sparkle", package: "Sparkle"),
            ],
            path: "Sources"
        ),
    ]
)
