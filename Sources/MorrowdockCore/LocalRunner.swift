import Foundation
/// Runs only the deterministic terminal simulator; never executes host processes.
public actor LocalRunner: CodeRunner {
 private var terminal=TerminalLab()
 public init() {}
 public func run(_ command: String) async throws -> String { try terminal.run(command) }
}
