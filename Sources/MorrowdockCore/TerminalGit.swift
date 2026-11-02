import Foundation

public struct TerminalCommitGraph: Codable, Equatable, Sendable {
    public struct Node: Codable, Equatable, Sendable {
        public var id: String
        public var parents: [String]
        public var message: String
        public var tree: [String: TerminalEntry]
    }
    public var nodes: [Node]
    public var branches: [String: String]
    public var head: String?
    public var currentBranch: String
}
/// Deliberately bounded Git teaching model: no remotes, hooks, executable files or host Git.
public struct TerminalGit: Codable, Sendable {
    public var root: String?
    public var commits: [TerminalCommitGraph.Node] = []
    public var branches: [String: String] = [:]
    public var currentBranch = "main"
    public var index: [String: TerminalEntry] = [:]
    public var graph: TerminalCommitGraph { .init(nodes: commits, branches: branches, head: branches[currentBranch], currentBranch: currentBranch) }
    public init() {}
    func tree(_ id: String?) -> [String: TerminalEntry] { commits.first { $0.id == id }?.tree ?? [:] }
    func working(_ shell: TerminalLab) -> [String: TerminalEntry] { shell.files.filter { !$0.value.directory && $0.key.hasPrefix((root ?? "") + "/") } }
    mutating func commit(_ message: String, parents: [String]) {
        let id = "c\(commits.count + 1)"; commits.append(.init(id: id, parents: parents, message: message, tree: index)); branches[currentBranch] = id
    }
    func ancestors(_ id: String) -> Set<String> {
        var seen: Set<String> = [], queue = [id]
        while let n = queue.popLast() { if seen.insert(n).inserted { queue += commits.first { $0.id == n }?.parents ?? [] } }; return seen
    }
    mutating func restore(_ target: [String: TerminalEntry], shell: inout TerminalLab) {
        for key in working(shell).keys { shell.files.removeValue(forKey: key) }
        for (key, entry) in target {
            var parent = (key as NSString).deletingLastPathComponent
            while parent != "/", !parent.isEmpty {
                shell.files[parent] = .init(directory: true)
                parent = (parent as NSString).deletingLastPathComponent
            }
            shell.files[key] = entry
        }; index = target
    }
    mutating func run(_ a: [String], shell: inout TerminalLab) throws -> String {
        func fail(_ s: String) -> TerminalLabError { .invalid(s) }
        guard let cmd = a.first else { throw fail("Choose a git command") }
        if cmd == "init" { guard root == nil else { return "Already initialized\n" }; root = shell.cwd; return "Initialized workspace\n" }
        guard let root, shell.cwd == root || shell.cwd.hasPrefix(root + "/") else { throw fail("Not in a repository") }
        let head = branches[currentBranch], base = tree(head), work = working(shell)
        switch cmd {
        case "add": guard a.count > 1 else { throw fail("Choose files") }; for name in a.dropFirst() { if name == "." { index = work } else { let p = shell.path(name); guard let e = work[p] else { if index[p] != nil { index.removeValue(forKey:p); continue }; throw fail("No file") }; index[p] = e } }; return ""
        case "commit": guard a.count == 3, a[1] == "-m", !a[2].isEmpty, index != base else { throw fail("Stage a change and use commit -m message") }; commit(a[2], parents: head.map { [$0] } ?? []); return "Committed\n"
        case "status": return "On branch \(currentBranch)\n" + (index == base && work == index ? "Working tree clean\n" : "Staged: \(index == base ? "no" : "yes")\nUnstaged: \(work == index ? "no" : "yes")\n")
        case "log": guard let head else { return "" }; let reachable = ancestors(head); return commits.reversed().filter { reachable.contains($0.id) }.map { "\($0.id) \($0.message)\n" }.joined()
        case "diff", "diff-lite": let lhs = a.contains("--cached") ? base : index, rhs = a.contains("--cached") ? index : work; return Set(lhs.keys).union(rhs.keys).sorted().filter { lhs[$0] != rhs[$0] }.map { "\($0)\n-\(lhs[$0]?.text ?? "")+\(rhs[$0]?.text ?? "")" }.joined()
        case "branch": if a.count == 1 { return branches.keys.sorted().map { ($0 == currentBranch ? "* " : "  ") + $0 + "\n" }.joined() }; guard a.count == 2, branches[a[1]] == nil, let head else { throw fail("Branch needs an existing commit and a new name") }; branches[a[1]] = head; return ""
        case "checkout", "switch": guard work == index, index == base else { throw fail("Commit or reset your changes first") }; let create = a.count == 3 && ["-b", "-c"].contains(a[1]); let name = a.last!; if create { guard branches[name] == nil, let head else { throw fail("Cannot create branch") }; branches[name] = head }; guard a.count == 2 || create, let target = branches[name] else { throw fail("Unknown branch") }; currentBranch = name; restore(tree(target), shell: &shell); return ""
        case "reset": guard a.count >= 2 else { throw fail("Choose --hard, --mixed or --soft and a commit") }; let mode = a[1]; guard ["--hard", "--mixed", "--soft"].contains(mode), let head else { throw fail("Invalid reset") }; let ref = a.count > 2 ? a[2] : head; let target = ref == "HEAD~1" ? commits.first { $0.id == head }?.parents.first : branches[ref] ?? commits.first { $0.id == ref }?.id; guard let target else { throw fail("Unknown commit") }; branches[currentBranch] = target; if mode == "--hard" { restore(tree(target), shell: &shell) } else if mode == "--mixed" { index = tree(target) }; return ""
        case "merge", "rebase", "rebase-lite":
            guard a.count == 2, let other = branches[a[1]], let head, work == index, index == base else { throw fail("Use a known branch with a clean workspace") }
            if ancestors(head).contains(other) { return "Already up to date\n" }
            if ancestors(other).contains(head) { branches[currentBranch] = other; restore(tree(other), shell: &shell); return "Fast-forward\n" }
            let common = commits.reversed().first { ancestors(head).contains($0.id) && ancestors(other).contains($0.id) }; let ancestorTree = common?.tree ?? [:], theirs = tree(other)
            var merged = theirs
            for key in Set(base.keys).union(ancestorTree.keys) where base[key] != ancestorTree[key] {
                guard theirs[key] == ancestorTree[key] || theirs[key] == base[key] else { throw fail("Conflict in \(key); workspace unchanged") }; merged[key] = base[key]
            }
            if cmd == "merge" { index = merged; commit("Merge \(a[1])", parents: [head, other]) }
            else { let replay = commits.filter { ancestors(head).contains($0.id) && !ancestors(other).contains($0.id) }; var previous = tree(other); branches[currentBranch] = other
                for old in replay { let oldBase = tree(old.parents.first); for key in Set(oldBase.keys).union(old.tree.keys) where oldBase[key] != old.tree[key] { previous[key] = old.tree[key] }; index = previous; commit(old.message, parents: [branches[currentBranch]!]) }
            }; restore(tree(branches[currentBranch]), shell: &shell); return ""
        default: throw fail("Unsupported git command")
        }
    }
}
