// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Moneta",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "Moneta", targets: ["Moneta"])],
    targets: [.executableTarget(name: "Moneta")]
)
