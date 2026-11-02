import Foundation

public protocol AIProvider { func respond(to text: String) async throws -> String }
public protocol CourseGenerator { func generate(topic: String) async throws -> Data }
public protocol CodeRunner { func run(_ command: String) async throws -> String }
public protocol SyncService { func synchronize(_ snapshot: Data) async throws -> Data }
public protocol CatalogService { func courses() async throws -> [CatalogRecord] }
public protocol AccountService { func account() async throws -> String? }
public protocol CreditsService { func balance() async throws -> Int? }
public struct CatalogRecord: Codable, Equatable, Sendable {
 public let id: String, version: String, checksum: String
 public init(id: String, version: String, checksum: String) { self.id=id; self.version=version; self.checksum=checksum }
}
public enum ServiceError: Error { case unavailable, invalidResponse, consentRequired, insecureEndpoint }
/// One operation per explicit invocation. Transports must not retry or follow redirects.
public struct ServiceRequest {
 public let url: URL, method: String, headers: [String:String], body: Data?
 public init(url: URL, method: String, headers: [String:String] = [:], body: Data? = nil) { self.url=url; self.method=method; self.headers=headers; self.body=body }
}
public struct ServiceResponse {
 public let status: Int, body: Data
 public init(status: Int, body: Data) { self.status=status; self.body=body }
}
public typealias ServiceTransport = (ServiceRequest) async throws -> ServiceResponse
public struct StaticCatalog: CatalogService {
 public let records: [CatalogRecord]
 public init(_ records: [CatalogRecord] = []) { self.records=records }
 public func courses() async throws -> [CatalogRecord] { records }
}
public struct LocalSync: SyncService {
 public init() {}
 public func synchronize(_ snapshot: Data) async throws -> Data { snapshot }
}
public struct LocalAccount: AccountService, CreditsService {
 public init() {}
 public func account() async throws -> String? { nil }
 public func balance() async throws -> Int? { nil }
}
/// On-device implementation supplied by the host (for example Apple Foundation Models).
/// The closure never selects a cloud fallback.
public struct OnDeviceAI: AIProvider {
 private let generate: (String) async throws -> String
 public init(generate: @escaping (String) async throws -> String) { self.generate=generate }
 public func respond(to text: String) async throws -> String { try await generate(text) }
}
public struct LocalCourseGenerator: CourseGenerator {
 private let generate: (String) async throws -> Data
 public init(generate: @escaping (String) async throws -> Data) { self.generate=generate }
 public func generate(topic: String) async throws -> Data { try await generate(topic) }
}
