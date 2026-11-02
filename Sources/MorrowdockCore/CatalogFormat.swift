import Foundation
/// An immutable registry pin; quality is assigned by maintainer review outside the course.
public struct CatalogPin: Codable, Sendable {
 public let id: String, repository: URL, commit: String, version: String, sha256: String, bundlePath: String
 public func validate() throws {
  guard !id.isEmpty, repository.scheme == "https", repository.host != nil,
   repository.user == nil, repository.password == nil, repository.query == nil, repository.fragment == nil,
   commit.range(of:"^[0-9a-f]{40}$",options:.regularExpression) != nil,
   sha256.range(of:"^[0-9a-f]{64}$",options:.regularExpression) != nil,
   version.range(of:"^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$",options:.regularExpression) != nil,
   !bundlePath.hasPrefix("/"), !bundlePath.contains("\\"), !bundlePath.contains(":"), !bundlePath.contains("%"),
   bundlePath.split(separator:"/",omittingEmptySubsequences:false).allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { throw CourseBundle.Invalid.reference }
 }
}
public extension ProjectStage {
 /// Format-only validation, never a host-code execution or verified-completion claim.
 func validate() throws {
  guard !id.isEmpty, !title.isEmpty, !goal.isEmpty, starterFiles.count <= 100,
   referenceFiles.count <= 100, visibleTests.count + hiddenTests.count <= 100 else { throw CourseBundle.Invalid.limit }
  for (name, source) in Array(starterFiles) + Array(referenceFiles) {
   guard !name.hasPrefix("/"), !name.contains("\\"), !name.contains(":"), source.utf8.count <= 1_000_000,
    name.split(separator:"/",omittingEmptySubsequences:false).allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else { throw CourseBundle.Invalid.reference }
  }
 }
}
