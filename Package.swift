// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "MorrowdockCore", platforms: [.macOS(.v14), .iOS(.v17)], products: [.library(name: "MorrowdockCore", targets: ["MorrowdockCore"])], targets: [.target(name: "MorrowdockCore"), .testTarget(name: "MorrowdockCoreTests", dependencies: ["MorrowdockCore"])], swiftLanguageModes: [.v5])
