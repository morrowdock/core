import XCTest
@testable import MorrowdockCore

final class TerminalLabTests: XCTestCase {
    func testAllThirtyMissionWalkthroughs() throws {
        XCTAssertEqual(TerminalMission.terminal.count, 20)
        XCTAssertEqual(TerminalMission.gitPuzzles.count, 10)
        for m in TerminalMission.terminal + TerminalMission.gitPuzzles {
            var s = m.start
            for c in m.solution { do { try s.run(c) } catch { XCTFail("\(m.id): \(c): \(error)"); throw error } }
            XCTAssertTrue(m.completed(in: s), m.id)
        }
    }
    func testQuotesExpansionGlobsAndRedirects() throws {
        var s = TerminalMission.seed
        XCTAssertEqual(try s.run("echo '$HOME' \"$HOME\""), "$HOME /home\n")
        XCTAssertEqual(try s.run("cat *.txt"), "alpha\nbeta\nalpha\n")
        XCTAssertEqual(try s.run("echo 'a|b > c'"), "a|b > c\n")
        try s.run("export X='a|b'")
        XCTAssertEqual(try s.run("echo $X"), "a|b\n")
        XCTAssertEqual(try s.run("cat < notes.txt | sort | uniq"), "alpha\nbeta\n")
        try s.run("echo '' > empty")
        XCTAssertEqual(try s.read("empty"), "\n")
        XCTAssertEqual(try s.run("echo one\\ two"), "one two\n")
        XCTAssertEqual(try s.run("echo ${HOME}"), "/home\n")
    }
    func testMalformedCommands() throws {
        for c in ["echo '", "echo x >", "| cat", "echo x |", "echo ${HOME", "echo \\", "cat missing", "chmod 999 notes.txt", "kill 1", "cd missing", "unknown"] {
            var s = TerminalMission.seed
            XCTAssertThrowsError(try s.run(c), c)
        }
    }
    func testRootConfinementAndDirectorySafety() throws {
        var s = TerminalMission.seed
        XCTAssertEqual(s.path("../../../../etc"), "/etc")
        XCTAssertThrowsError(try s.run("cat /etc/passwd"))
        XCTAssertThrowsError(try s.run("rm -r /"))
        XCTAssertThrowsError(try s.run("rm -r /home"))
        XCTAssertThrowsError(try s.run("rm logs"))
        try s.run("rm -r logs")
        XCTAssertNil(s.files["/home/logs/app.log"])
        XCTAssertThrowsError(try s.run("echo x > missing/file"))
    }
    func testInspectionCommands() throws {
        var s = TerminalMission.seed
        XCTAssertTrue(try s.run("ls").contains("notes.txt"))
        XCTAssertEqual(try s.run("pwd"), "/home\n")
        XCTAssertEqual(try s.run("which grep"), "/bin/grep\n")
        XCTAssertTrue(try s.run("man-lite grep").contains("grep"))
        XCTAssertTrue(try s.run("ps").contains("42 practice-worker"))
        XCTAssertTrue(try s.run("env").contains("HOME=/home"))
        XCTAssertTrue(try s.run("history").contains("history"))
        XCTAssertEqual(try s.run("wc notes.txt"), "3 3 17\n")
    }
    func testPersistenceRoundTrip() throws {
        var s = TerminalMission.gitPuzzles[0].start
        for c in TerminalMission.gitPuzzles[0].solution { try s.run(c) }
        let copy = try JSONDecoder().decode(TerminalLab.self, from: JSONEncoder().encode(s))
        XCTAssertEqual(s.files, copy.files); XCTAssertEqual(s.git.graph, copy.git.graph)
    }
    func testConflictAndDirtySwitchPreserveWork() throws {
        var s = TerminalMission.gitPuzzles[1].start
        for c in ["git branch feature", "echo main > notes.txt", "git add .", "git commit -m main", "git switch feature", "echo feature > notes.txt", "git add .", "git commit -m feature"] { try s.run(c) }
        let before = s.files, graph = s.git.graph
        XCTAssertThrowsError(try s.run("git merge main"))
        XCTAssertEqual(before, s.files); XCTAssertEqual(graph, s.git.graph)
        try s.run("echo dirty > notes.txt")
        XCTAssertThrowsError(try s.run("git switch main"))
        XCTAssertEqual(try s.read("notes.txt"), "dirty\n")
    }
    func testIndexIsSnapshotAndResetModes() throws {
        var s = TerminalMission.gitPuzzles[1].start
        try s.run("echo staged > notes.txt"); try s.run("git add notes.txt"); try s.run("echo later > notes.txt")
        XCTAssertTrue(try s.run("git diff").contains("later"))
        try s.run("git commit -m staged")
        XCTAssertEqual(s.git.commits.last?.tree["/home/notes.txt"]?.text, "staged\n")
        try s.run("git reset --soft HEAD~1")
        XCTAssertEqual(s.git.index["/home/notes.txt"]?.text, "staged\n")
        try s.run("git reset --mixed")
        XCTAssertEqual(try s.read("notes.txt"), "later\n")
        try s.run("git reset --hard")
        XCTAssertEqual(try s.read("notes.txt"), "alpha\nbeta\nalpha\n")
    }
    func testGraphParentsAndUnreachableResetHistory() throws {
        let m = TerminalMission.gitPuzzles[7]; var s = m.start
        for c in m.solution { try s.run(c) }
        let graph = s.git.graph
        XCTAssertEqual(graph.nodes.last?.parents.count, 2)
        XCTAssertEqual(graph.head, graph.branches[graph.currentBranch])
        for node in graph.nodes { for parent in node.parents { XCTAssertTrue(graph.nodes.contains { $0.id == parent }) } }
        XCTAssertTrue(try s.run("git log").contains("Merge"))
        try s.run("git reset --hard HEAD~1")
        XCTAssertFalse(try s.run("git log").contains("Merge"))
        XCTAssertEqual(s.git.graph.nodes.count, graph.nodes.count)
    }
    func testRestoreNestedCommittedFiles() throws {
        var s = TerminalLab()
        for c in ["mkdir nested", "echo x > nested/x", "git init", "git add .", "git commit -m start", "rm -r nested", "git reset --hard"] { try s.run(c) }
        XCTAssertEqual(try s.read("nested/x"), "x\n")
        try s.run("cd nested")
        XCTAssertEqual(s.cwd, "/home/nested")
    }
    func testGlobBoundariesAndCommandLimits() throws {
        XCTAssertTrue(TerminalLab.matches("a.txt", "?.txt"))
        XCTAssertFalse(TerminalLab.matches("a/b.txt", "*.txt"))
        var s = TerminalMission.seed
        XCTAssertEqual(try s.run("echo '*.txt'"), "*.txt\n")
        XCTAssertEqual(try s.run("echo no-match*.x"), "no-match*.x\n")
        XCTAssertThrowsError(try s.run(String(repeating: "x", count: 16385)))
        XCTAssertThrowsError(try s.run("grep '[' notes.txt"))
        XCTAssertThrowsError(try s.run("git status"))
    }

}
