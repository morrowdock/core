import Foundation

public struct TerminalMission: Codable, Sendable, Identifiable {
    public enum Goal: Codable, Sendable {
        case file(String, String), absent(String), directory(String), cwd(String), mode(String, String), environment(String, String), processAbsent(Int), branch(String), commits(Int), clean, merge
        public func passes(_ s: TerminalLab) -> Bool {
            switch self {
            case .file(let p, let t): return s.files[s.path(p)]?.text == t && s.files[s.path(p)]?.directory == false
            case .absent(let p): return s.files[s.path(p)] == nil
            case .directory(let p): return s.files[s.path(p)]?.directory == true
            case .cwd(let p): return s.cwd == p
            case .mode(let p, let m): return s.files[s.path(p)]?.mode == m
            case .environment(let k, let v): return s.environment[k] == v
            case .processAbsent(let pid): return s.processes[pid] == nil
            case .branch(let b): return s.git.currentBranch == b
            case .commits(let n): return s.git.commits.count == n
            case .clean: return s.git.root != nil && s.git.index == s.files.filter { !$0.value.directory && $0.key.hasPrefix(s.git.root! + "/") } && s.git.index == s.git.commits.first { $0.id == s.git.graph.head }?.tree
            case .merge: return s.git.commits.contains { $0.parents.count == 2 }
            }
        }
    }
    public let id: String
    public let title: String
    public let instruction: String
    public let start: TerminalLab
    public let goals: [Goal]
    public let hints: [String]
    /// Validation walkthrough, kept separate from what the terminal view displays.
    public let solution: [String]
    public func completed(in shell: TerminalLab) -> Bool { !goals.isEmpty && goals.allSatisfy { $0.passes(shell) } }
    public static var terminal: [Self] {
        let rows: [(String, String, [String], [Goal])] = [
            ("Find your feet", "Move into the logs folder.", ["cd logs"], [.cwd("/home/logs")]),
            ("A first note", "Write ready into ready.txt.", ["echo ready > ready.txt"], [.file("/home/ready.txt", "ready\n")]),
            ("Room to work", "Create a projects folder.", ["mkdir projects"], [.directory("/home/projects")]),
            ("Blank slate", "Create empty.txt without any text.", ["touch empty.txt"], [.file("/home/empty.txt", "")]),
            ("Make a copy", "Copy roster.csv to backup.csv.", ["cp roster.csv backup.csv"], [.file("/home/backup.csv", "Ada,pilot\nLin,engineer\n")]),
            ("Rename the log", "Rename notes.txt to journal.txt.", ["mv notes.txt journal.txt"], [.absent("/home/notes.txt"), .file("/home/journal.txt", "alpha\nbeta\nalpha\n")]),
            ("Clear the draft", "Remove notes.txt.", ["rm notes.txt"], [.absent("/home/notes.txt")]),
            ("One more line", "Append gamma to notes.txt.", ["echo gamma >> notes.txt"], [.file("/home/notes.txt", "alpha\nbeta\nalpha\ngamma\n")]),
            ("Spot the error", "Save ERROR lines from logs/app.log to errors.txt.", ["grep ERROR logs/app.log > errors.txt"], [.file("/home/errors.txt", "ERROR sensor\n")]),
            ("First report", "Save the first line of notes.txt to first.txt.", ["head -n 1 notes.txt > first.txt"], [.file("/home/first.txt", "alpha\n")]),
            ("Last report", "Save the last line to last.txt.", ["tail -n 1 notes.txt > last.txt"], [.file("/home/last.txt", "alpha\n")]),
            ("Count the lines", "Write the line count of notes.txt to count.txt.", ["cat notes.txt | wc -l > count.txt"], [.file("/home/count.txt", "3\n")]),
            ("Tidy the list", "Sort and deduplicate notes into unique.txt.", ["sort notes.txt | uniq > unique.txt"], [.file("/home/unique.txt", "alpha\nbeta\n")]),
            ("Names only", "Extract roster names into names.txt.", ["cut -d , -f 1 roster.csv > names.txt"], [.file("/home/names.txt", "Ada\nLin\n")]),
            ("Permission repair", "Give notes.txt mode 600.", ["chmod 600 notes.txt"], [.mode("/home/notes.txt", "600")]),
            ("Stop the worker", "Stop practice-worker while keeping your shell.", ["kill 42"], [.processAbsent(42)]),
            ("Name your route", "Set ROUTE to coastal flight.", ["export ROUTE='coastal flight'"], [.environment("ROUTE", "coastal flight")]),
            ("Quoted cargo", "Create flight plan.txt containing go home.", ["echo 'go home' > 'flight plan.txt'"], [.file("/home/flight plan.txt", "go home\n")]),
            ("Follow the variable", "Write your home path to home.txt using HOME.", ["echo \"$HOME\" > home.txt"], [.file("/home/home.txt", "/home\n")]),
            ("Log scout", "Find log files under logs and save their paths to paths.txt.", ["find logs -name '*.log' > paths.txt"], [.file("/home/paths.txt", "/home/logs/app.log\n")])
        ]
        return rows.enumerated().map { i, r in .init(id: "terminal-\(i+1)", title: r.0, instruction: r.1, start: seed, goals: r.3, hints: ["Try \(r.2[0].split(separator: " ")[0]).", r.2.joined(separator: "\n")], solution: r.2) }
    }
    public static var seed: TerminalLab {
        var s = TerminalLab(); s.files["/home/logs"] = .init(directory: true)
        s.files["/home/logs/app.log"] = .init(text: "OK boot\nERROR sensor\nOK retry\n")
        s.files["/home/notes.txt"] = .init(text: "alpha\nbeta\nalpha\n")
        s.files["/home/roster.csv"] = .init(text: "Ada,pilot\nLin,engineer\n"); return s
    }
    public static var gitPuzzles: [Self] {
        let setups: [(String, [String], [Goal])] = [
            ("First snapshot", ["git init", "git add .", "git commit -m launch"], [.commits(1), .clean]),
            ("A feature branch", ["git branch feature", "git switch feature"], [.branch("feature"), .clean]),
            ("Stage then commit", ["echo wing > wing.txt", "git add wing.txt", "git commit -m wing"], [.commits(2), .clean]),
            ("Switch home", ["git switch -c feature", "git switch main"], [.branch("main"), .clean]),
            ("Fast forward", ["git switch -c feature", "echo wing > wing.txt", "git add .", "git commit -m wing", "git switch main", "git merge feature"], [.file("/home/wing.txt", "wing\n"), .branch("main"), .clean]),
            ("Undo a draft", ["echo draft > draft.txt", "git reset --hard"], [.absent("/home/draft.txt"), .clean]),
            ("Back one snapshot", ["echo wing > wing.txt", "git add .", "git commit -m wing", "git reset --hard HEAD~1"], [.absent("/home/wing.txt"), .clean]),
            ("Two routes meet", ["git branch feature", "echo main > main.txt", "git add .", "git commit -m main", "git switch feature", "echo wing > wing.txt", "git add .", "git commit -m wing", "git switch main", "git merge feature"], [.merge, .clean]),
            ("Replay your route", ["git branch feature", "echo main > main.txt", "git add .", "git commit -m main", "git switch feature", "echo wing > wing.txt", "git add .", "git commit -m wing", "git rebase-lite main"], [.branch("feature"), .file("/home/main.txt", "main\n"), .file("/home/wing.txt", "wing\n"), .commits(4), .clean]),
            ("Commit a removal", ["rm notes.txt", "git add .", "git commit -m cleanup"], [.absent("/home/notes.txt"), .commits(2), .clean])
        ]
        return setups.enumerated().map { i, row in
            var s = seed
            if i != 0 { for c in ["git init", "git add .", "git commit -m start"] { _ = try? s.run(c) } }
            return .init(id: "git-\(i+1)", title: row.0, instruction: i == 0 ? "Create your first commit with all starter files." : "\(row.0). Use the hints to plan your commands.", start: s, goals: row.2, hints: [row.1.joined(separator: "\n")], solution: row.1)
        }
    }
}
