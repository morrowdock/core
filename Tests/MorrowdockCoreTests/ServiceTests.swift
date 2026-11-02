import XCTest
@testable import MorrowdockCore
final class ServiceTests: XCTestCase {
 func testLocalBuildWithoutPlus() async throws { let v=try await StaticCatalog().courses(); XCTAssertEqual(v,[]); let credits=try await LocalAccount().balance(); XCTAssertNil(credits) }
 func testChangedConsentNeverSends() async throws {
  let p=DirectProvider(vendor:.openAI,model:"synthetic",key:"fixture",approvedText:"reviewed",transport:{ _ in XCTFail("must not send"); throw ServiceError.invalidResponse })
  do { _ = try await p.respond(to:"changed"); XCTFail() } catch {}
 }
 func testPlusRejectsInsecureOrigin() { XCTAssertThrowsError(try PlusClient(base:URL(string:"http://example.invalid")!,token:"fixture",transport:{ _ in throw ServiceError.unavailable })) }
 func testAllProviderWireShapes() async throws {
  for vendor in [DirectProvider.Vendor.openAI,.anthropic,.openRouter,.gemini] {
   let p=DirectProvider(vendor:vendor,model:"synthetic",key:"fixture",approvedText:"hello",transport:{ request in
    XCTAssertEqual(request.method,"POST"); XCTAssertEqual(request.url.scheme,"https")
    let json: String
    switch vendor { case .openAI: json="{\"output\":[{\"content\":[{\"text\":\"ok\"}]}]}"; case .anthropic: json="{\"content\":[{\"text\":\"ok\"}]}"; case .openRouter: json="{\"choices\":[{\"message\":{\"content\":\"ok\"}}]}"; case .gemini: json="{\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"ok\"}]}}]}" }
    return .init(status:200,body:Data(json.utf8))
   }); let result=try await p.respond(to:"hello"); XCTAssertEqual(result,"ok")
  }
 }
}
