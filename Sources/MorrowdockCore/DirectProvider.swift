import Foundation
/// Explicit BYOK run: caller supplies the key and approved text for this invocation only.
/// No credential storage, retries, fallback, account or Plus requirement.
public struct DirectProvider: AIProvider {
 public enum Vendor { case openAI, anthropic, openRouter, gemini }
 private let vendor: Vendor, model: String, key: String, approvedText: String, transport: ServiceTransport
 public init(vendor: Vendor, model: String, key: String, approvedText: String, transport: @escaping ServiceTransport) {
  self.vendor=vendor; self.model=model; self.key=key; self.approvedText=approvedText; self.transport=transport
 }
 public func respond(to text: String) async throws -> String {
  guard text == approvedText, !key.isEmpty else { throw ServiceError.consentRequired }
  var headers = ["Content-Type":"application/json"]
  let url: URL; let body: [String:Any]
  switch vendor {
  case .openAI:
   url=URL(string:"https://api.openai.com/v1/responses")!; headers["Authorization"]="Bearer " + key
   body=["model":model,"input":text,"store":false]
  case .anthropic:
   url=URL(string:"https://api.anthropic.com/v1/messages")!; headers["x-api-key"]=key; headers["anthropic-version"]="2023-06-01"
   body=["model":model,"max_tokens":1024,"messages":[["role":"user","content":text]]]
  case .openRouter:
   url=URL(string:"https://openrouter.ai/api/v1/chat/completions")!; headers["Authorization"]="Bearer " + key
   body=["model":model,"messages":[["role":"user","content":text]]]
  case .gemini:
   guard model.range(of:"^[A-Za-z0-9._-]+$",options:.regularExpression) != nil else { throw ServiceError.invalidResponse }
   url=URL(string:"https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent")!; headers["x-goog-api-key"]=key
   body=["contents":[["parts":[["text":text]]]]]
  }
  let response=try await transport(.init(url:url,method:"POST",headers:headers,body:JSONSerialization.data(withJSONObject:body)))
  guard (200..<300).contains(response.status), response.body.count <= 2_000_000,
        let object=try JSONSerialization.jsonObject(with:response.body) as? [String:Any] else { throw ServiceError.invalidResponse }
  let answer: String?
  switch vendor {
  case .openAI:
   answer=(object["output"] as? [[String:Any]])?.flatMap { $0["content"] as? [[String:Any]] ?? [] }.compactMap { $0["text"] as? String }.joined()
  case .anthropic: answer=(object["content"] as? [[String:Any]])?.compactMap { $0["text"] as? String }.joined()
  case .openRouter: answer=(((object["choices"] as? [[String:Any]])?.first)?["message"] as? [String:Any])?["content"] as? String
  case .gemini: answer=((((object["candidates"] as? [[String:Any]])?.first)?["content"] as? [String:Any])?["parts"] as? [[String:Any]])?.compactMap { $0["text"] as? String }.joined()
  }
  guard let answer, !answer.isEmpty else { throw ServiceError.invalidResponse }; return answer
 }
}
