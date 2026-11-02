import Foundation

public enum TerminalLabError: Error, CustomStringConvertible {
    case invalid(String)
    public var description: String { switch self { case .invalid(let s): return s } }
}
public struct TerminalEntry: Codable, Equatable, Sendable {
    public var directory: Bool
    public var text: String
    public var mode: String
    public init(directory: Bool = false, text: String = "", mode: String = "644") {
        self.directory = directory; self.text = text; self.mode = mode
    }
}
/// Entirely virtual. No Foundation filesystem, Process, network or host environment access.
public struct TerminalLab: Codable, Sendable {
    public var files: [String: TerminalEntry] = ["/": .init(directory: true), "/home": .init(directory: true)]
    public var cwd = "/home"
    public var environment = ["HOME": "/home", "USER": "learner"]
    public var history: [String] = []
    public var processes = [1: "shell", 42: "practice-worker"]
    public var git = TerminalGit()
    public init() {}
    public func path(_ s: String) -> String {
        let s = s == "~" ? "/home" : s.hasPrefix("~/") ? "/home/" + s.dropFirst(2) : s
        var parts: [String] = []
        for p in (s.hasPrefix("/") ? s : cwd + "/" + s).split(separator: "/") {
            if p == ".." { if !parts.isEmpty { parts.removeLast() } }
            else if p != "." { parts.append(String(p)) }
        }
        return "/" + parts.joined(separator: "/")
    }
    public mutating func write(_ name: String, _ text: String) throws {
        let p = path(name), parent = (p as NSString).deletingLastPathComponent
        guard files[parent]?.directory == true, files[p]?.directory != true else { throw TerminalLabError.invalid("Not a writable file: \(name)") }
        files[p] = .init(text: text, mode: files[p]?.mode ?? "644")
    }
    public func read(_ name: String) throws -> String {
        guard let e = files[path(name)], !e.directory else { throw TerminalLabError.invalid("No file: \(name)") }; return e.text
    }
    struct Token { var value: String; var literal: Bool }
    /// Quotes protect operators and globs; expansion happens while lexing so expanded pipes remain data.
    func tokens(_ source: String) throws -> [Token] {
        let chars = Array(source); var i = 0, word = "", active = false, literal = false
        var quote: Character?; var result: [Token] = []
        func flush() { if active { result.append(.init(value: word, literal: literal)); word = ""; active = false; literal = false } }
        while i < chars.count {
            let c = chars[i]
            if c == "\\", quote != "'" { i += 1; guard i < chars.count else { throw TerminalLabError.invalid("Trailing escape") }; word.append(chars[i]); active = true; literal = true }
            else if c == "'" || c == "\"" { if quote == c { quote = nil } else if quote == nil { quote = c; literal = true; active = true } else { word.append(c) } }
            else if c == "$", quote != "'" {
                i += 1; var key = ""
                if i < chars.count, chars[i] == "{" { i += 1; while i < chars.count, chars[i] != "}" { key.append(chars[i]); i += 1 }; guard i < chars.count else { throw TerminalLabError.invalid("Unclosed variable") } }
                else { while i < chars.count, chars[i].isLetter || chars[i].isNumber || chars[i] == "_" { key.append(chars[i]); i += 1 }; i -= 1 }
                word += environment[key] ?? ""; active = true
            }
            else if quote == nil, c.isWhitespace { flush() }
            else if quote == nil, "|<>".contains(c) { flush(); var op = String(c); if c == ">", i+1 < chars.count, chars[i+1] == ">" { op = ">>"; i += 1 }; result.append(.init(value: op, literal: false)) }
            else { word.append(c); active = true }
            i += 1
        }
        guard quote == nil else { throw TerminalLabError.invalid("Unclosed quote") }; flush(); return result
    }
    public static func matches(_ value: String, _ glob: String) -> Bool {
        let pattern = "^" + glob.map { c in c == "*" ? "[^/]*" : c == "?" ? "[^/]" : NSRegularExpression.escapedPattern(for: String(c)) }.joined() + "$"
        return value.range(of: pattern, options: .regularExpression) != nil
    }
    @discardableResult public mutating func run(_ source: String) throws -> String {
        guard source.utf8.count <= 16384 else { throw TerminalLabError.invalid("Command too long") }
        let ts = try tokens(source); history.append(source)
        var stages: [[String]] = [[]]; var output: (String, Bool)?; var input: String?; var i = 0
        while i < ts.count {
            let t = ts[i]
            if !t.literal, t.value == "|" { guard !stages.last!.isEmpty, output == nil else { throw TerminalLabError.invalid("Invalid pipe") }; stages.append([]) }
            else if !t.literal, [">", ">>", "<"].contains(t.value) {
                i += 1; guard i < ts.count, ts[i].literal || !["|", ">", ">>", "<"].contains(ts[i].value) else { throw TerminalLabError.invalid("Missing redirect target") }
                if t.value == "<" { input = ts[i].value } else { output = (ts[i].value, t.value == ">>") }
            } else {
                let matches = !t.literal && (t.value.contains("*") || t.value.contains("?")) ? files.keys.filter { Self.matches($0, path(t.value)) }.sorted() : []
                stages[stages.count-1] += matches.isEmpty ? [t.value] : matches
            }; i += 1
        }
        if stages == [[]] { return "" }; guard !stages.last!.isEmpty else { throw TerminalLabError.invalid("Missing command") }
        var stream = try input.map { try read($0) } ?? ""
        for stage in stages { stream = try command(stage, input: stream) }
        if let (target, append) = output { try write(target, (append ? (try? read(target)) ?? "" : "") + stream); return "" }; return stream
    }
    mutating func command(_ a: [String], input: String) throws -> String {
        let cmd = a[0], args = Array(a.dropFirst())
        func arg(_ n: Int = 0) throws -> String { guard args.indices.contains(n) else { throw TerminalLabError.invalid("Missing argument for \(cmd)") }; return args[n] }
        func content() throws -> String { args.isEmpty ? input : try args.map { try read($0) }.joined() }
        func lines(_ text: String) -> [String] { var l = text.components(separatedBy: "\n"); if l.last == "" { l.removeLast() }; return l }
        func joined(_ l: [String]) -> String { l.isEmpty ? "" : l.joined(separator: "\n") + "\n" }
        switch cmd {
        case "pwd": return cwd + "\n"
        case "echo": return args.joined(separator: " ") + "\n"
        case "cat": return try content()
        case "cd": let p = path(args.first ?? "~"); guard files[p]?.directory == true else { throw TerminalLabError.invalid("No directory") }; cwd = p
        case "ls": let p = path(args.first ?? cwd); guard let e = files[p] else { throw TerminalLabError.invalid("No path") }; return e.directory ? joined(files.keys.filter { $0 != p && ($0 as NSString).deletingLastPathComponent == p }.map { ($0 as NSString).lastPathComponent }.sorted()) : p + "\n"
        case "touch": for n in args { if files[path(n)] == nil { try write(n, "") } }
        case "mkdir": for n in args { let p = path(n); guard files[p] == nil, files[(p as NSString).deletingLastPathComponent]?.directory == true else { throw TerminalLabError.invalid("Cannot create directory") }; files[p] = .init(directory: true) }
        case "rm": let recursive = args.contains("-r"); for n in args.filter({ $0 != "-r" }) { let p = path(n); guard p != "/", p != cwd, !cwd.hasPrefix(p + "/"), files[p] != nil else { throw TerminalLabError.invalid("Cannot remove path") }; let children = files.keys.filter { $0.hasPrefix(p + "/") }; guard recursive || children.isEmpty else { throw TerminalLabError.invalid("Directory not empty") }; for k in children + [p] { files.removeValue(forKey: k) } }
        case "cp", "mv": let src = path(try arg()), dst = path(try arg(1)); guard let e = files[src], !e.directory else { throw TerminalLabError.invalid("Only file copies supported") }; try write(dst, e.text); files[dst]?.mode = e.mode; if cmd == "mv", src != dst { files.removeValue(forKey: src) }
        case "head", "tail": let count = args.first == "-n" ? Int(try arg(1)) ?? -1 : 10; guard count >= 0 else { throw TerminalLabError.invalid("Invalid count") }; let names = args.first == "-n" ? Array(args.dropFirst(2)) : args; let text = names.isEmpty ? input : try names.map { try read($0) }.joined(); return joined(cmd == "head" ? Array(lines(text).prefix(count)) : Array(lines(text).suffix(count)))
        case "wc": let text = args.filter { !$0.hasPrefix("-") }; let s = text.isEmpty ? input : try text.map { try read($0) }.joined(); if args.contains("-l") { return "\(s.filter { $0 == "\n" }.count)\n" }; return "\(lines(s).count) \(s.split(whereSeparator: { $0.isWhitespace }).count) \(s.utf8.count)\n"
        case "grep": let pattern = try arg(); let text = args.count > 1 ? try args.dropFirst().map { try read($0) }.joined() : input; guard (try? NSRegularExpression(pattern: pattern)) != nil else { throw TerminalLabError.invalid("Invalid pattern") }; return joined(lines(text).filter { $0.range(of: pattern, options: .regularExpression) != nil })
        case "sort": return joined(lines(try content()).sorted())
        case "uniq": var out: [String] = []; for l in lines(try content()) { if out.last != l { out.append(l) } }; return joined(out)
        case "cut": guard args.count >= 4, args[0] == "-d", args[2] == "-f", let field = Int(args[3]), field > 0, !args[1].isEmpty else { throw TerminalLabError.invalid("Use cut -d delimiter -f field") }; let text = args.count > 4 ? try read(args[4]) : input; return joined(lines(text).map { let p = $0.components(separatedBy: args[1]); return p.indices.contains(field-1) ? p[field-1] : "" })
        case "find": let root = path(args.first ?? cwd); guard files[root] != nil else { throw TerminalLabError.invalid("No path") }; let pattern = args.count == 3 && args[1] == "-name" ? args[2] : "*"; return joined(files.keys.filter { ($0 == root || $0.hasPrefix(root + "/") || root == "/") && Self.matches(($0 as NSString).lastPathComponent, pattern) }.sorted())
        case "chmod": let mode = try arg(); guard mode.count == 3, mode.allSatisfy({ "01234567".contains($0) }), files[path(try arg(1))] != nil else { throw TerminalLabError.invalid("Use octal permissions") }; files[path(try arg(1))]?.mode = mode
        case "ps": return joined(processes.keys.sorted().map { "\($0) \(processes[$0]!)" })
        case "kill": guard let pid = Int(try arg()), pid != 1, processes.removeValue(forKey: pid) != nil else { throw TerminalLabError.invalid("No killable process") }
        case "env": return joined(environment.keys.sorted().map { "\($0)=\(environment[$0]!)" })
        case "export": let pair = try arg().split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false); guard pair.count == 2, !pair[0].isEmpty else { throw TerminalLabError.invalid("Use NAME=value") }; environment[String(pair[0])] = String(pair[1])
        case "history": return joined(history)
        case "which": let name = try arg(); guard Self.commands.contains(name) else { throw TerminalLabError.invalid("Unknown command") }; return "/bin/\(name)\n"
        case "man", "man-lite": let name = try arg(); guard Self.commands.contains(name) else { throw TerminalLabError.invalid("No manual") }; return "\(name): Practice in a virtual workspace. Pipes pass text; > replaces a file; >> appends.\n"
        case "git": var model = git; let result = try model.run(args, shell: &self); git = model; return result
        default: throw TerminalLabError.invalid("Unknown command: \(cmd)")
        }; return ""
    }
    public static let commands = "ls cd pwd cat echo touch mkdir rm cp mv head tail wc grep find sort uniq cut chmod ps kill env export which history man man-lite git".split(separator: " ").map(String.init)
}
