#if canImport(FoundationModels)
import FoundationModels
@available(macOS 26.0, iOS 26.0, *)
public struct AppleProvider: AIProvider {
 public init() {}
 public func respond(to text: String) async throws -> String {
  guard case .available = SystemLanguageModel.default.availability else { throw ServiceError.unavailable }
  return try await LanguageModelSession().respond(to: text).content
 }
}
#endif
