import Foundation
/// Open transport client for the proposed public Plus contract. No private prompts or routing.
public struct PlusClient: AccountService, CreditsService, CatalogService {
 private let base: URL, token: String, transport: ServiceTransport
 public init(base: URL, token: String, transport: @escaping ServiceTransport) throws {
  guard base.scheme == "https", base.host != nil, base.user == nil, base.password == nil, base.query == nil, base.fragment == nil else { throw ServiceError.insecureEndpoint }
  self.base=base; self.token=token; self.transport=transport
 }
 private func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
  let response=try await transport(.init(url:base.appendingPathComponent("v1/" + path),method:"GET",headers:["Authorization":"Bearer " + token]))
  guard response.status == 200, response.body.count <= 2_000_000 else { throw ServiceError.invalidResponse }
  return try JSONDecoder().decode(T.self,from:response.body)
 }
 public func account() async throws -> String? { struct Reply:Decodable { let accountID:String? }; return try await get("account",as:Reply.self).accountID }
 public func balance() async throws -> Int? { struct Reply:Decodable { let credits:Int? }; let value=try await get("credits",as:Reply.self).credits; guard value == nil || value! >= 0 else { throw ServiceError.invalidResponse }; return value }
 public func courses() async throws -> [CatalogRecord] { try await get("catalog",as:[CatalogRecord].self) }
}
