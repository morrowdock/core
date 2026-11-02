import XCTest
@testable import MorrowdockCore
final class FormatTests: XCTestCase {
 func testRegistryTraversalRejected() throws {
  let raw: [String:Any] = ["id":"demo","repository":"https://example.invalid/course","commit":String(repeating:"a",count:40),"version":"1.0.0","sha256":String(repeating:"b",count:64),"bundlePath":"../private"]
  let pin=try JSONDecoder().decode(CatalogPin.self,from:JSONSerialization.data(withJSONObject:raw))
  XCTAssertThrowsError(try pin.validate())
 }
 func testRegistryPinValid() throws {
  let raw: [String:Any] = ["id":"demo","repository":"https://example.invalid/course","commit":String(repeating:"a",count:40),"version":"1.0.0","sha256":String(repeating:"b",count:64),"bundlePath":"demo/bundle.json"]
  let pin=try JSONDecoder().decode(CatalogPin.self,from:JSONSerialization.data(withJSONObject:raw))
  XCTAssertNoThrow(try pin.validate())
 }
}
