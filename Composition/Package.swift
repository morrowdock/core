// swift-tools-version: 6.0
import PackageDescription
import Foundation
var packages: [Package.Dependency] = [.package(path: "..")]
var products: [Target.Dependency] = [.product(name: "MorrowdockCore", package: "core")]
if let path = ProcessInfo.processInfo.environment["MORROWDOCK_PRIVATE_PACKAGE"], !path.isEmpty {
 packages.append(.package(name: "MorrowdockPrivate", path: path))
 products.append(.product(name: "MorrowdockPrivate", package: "MorrowdockPrivate"))
}
let package = Package(name: "MorrowdockComposition", platforms: [.macOS(.v14), .iOS(.v17)], products: [.library(name: "MorrowdockComposition", targets: ["MorrowdockComposition"])], dependencies: packages, targets: [.target(name: "MorrowdockComposition", dependencies: products)])
