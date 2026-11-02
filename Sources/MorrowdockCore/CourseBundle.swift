import Foundation

public struct CourseBundle: Codable, Equatable, Sendable {
    public struct Named: Codable, Equatable, Sendable { public let id: String; public let title: String }
    public struct Material: Codable, Equatable, Sendable { public let id: String; public let title: String; public let ref: String }
    public struct Assignment: Codable, Equatable, Sendable { public let id: String; public let title: String; public let topicID: String; public let due: String; public init(id: String, title: String, topicID: String, due: String) { self.id = id; self.title = title; self.topicID = topicID; self.due = due } }
    public struct Question: Codable, Equatable, Sendable, Identifiable {
        public let id: String; public let topicID: String; public let prompt: String; public let choices: [String]
        public let answer: Int; public let explanation: String; public let materialID: String
    }
    public struct Blueprint: Codable, Equatable, Sendable { public let questionCount: Int; public let minutes: Int; public let points: Int }
    public let format: String; public let version: Int; public let course: Named; public let topics: [Named]
    public let materials: [Material]; public var assignments: [Assignment]; public let questions: [Question]
    public let examBlueprint: Blueprint; public let equationSheet: String?
    public enum Invalid: Error { case malformed, unsupported, reference, duplicate, limit }
    public static func decode(_ data: Data) throws -> Self {
        guard data.count <= 8_000_000 else { throw Invalid.limit }
        // Check every object for unknown AND missing fields before Codable decoding.
        let raw = try JSONSerialization.jsonObject(with: data)
        func keys(_ value: Any, _ expected: String) throws {
            guard let d = value as? [String: Any], Set(d.keys) == Set(expected.split(separator: " ").map(String.init)) else { throw Invalid.malformed }
        }
        try keys(raw, "format version course topics materials assignments questions examBlueprint equationSheet")
        guard let d = raw as? [String: Any] else { throw Invalid.malformed }
        try keys(d["course"] as Any, "id title"); try keys(d["examBlueprint"] as Any, "questionCount minutes points")
        for (key, fields) in [("topics", "id title"), ("materials", "id title ref"), ("assignments", "id title topicID due"), ("questions", "id topicID prompt choices answer explanation materialID")] {
            guard let rows = d[key] as? [Any], rows.count <= 10000 else { throw Invalid.limit }
            for row in rows { try keys(row, fields) }
        }
        let value = try JSONDecoder().decode(Self.self, from: data)
        try value.validate(); return value
    }
    public func validate() throws {
        guard format == "morrowdock-course-bundle", version == 1 else { throw Invalid.unsupported }
        func text(_ s: String, _ max: Int = 12000) throws {
            guard !s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, s.count <= max else { throw Invalid.malformed }
        }
        func ids(_ values: [String]) throws {
            guard Set(values).count == values.count else { throw Invalid.duplicate }
            for v in values { guard v.range(of: "^[A-Za-z0-9_-]{1,80}$", options: .regularExpression) != nil else { throw Invalid.malformed } }
        }
        try ids([course.id]); try text(course.title, 200)
        try ids(topics.map(\.id)); try ids(materials.map(\.id)); try ids(assignments.map(\.id)); try ids(questions.map(\.id))
        for t in topics { try text(t.title, 200) }
        for m in materials {
            try text(m.title, 200); try text(m.ref, 2048)
            guard Self.safePath(m.ref) || (URL(string: m.ref).map { $0.scheme == "https" && $0.host != nil && $0.user == nil && $0.password == nil } ?? false) else { throw Invalid.reference }
        }
        for a in assignments {
            try text(a.title, 200)
            guard topics.contains(where: { $0.id == a.topicID }), ISO8601DateFormatter().date(from: a.due) != nil else { throw Invalid.reference }
        }
        for q in questions {
            try text(q.prompt); try text(q.explanation)
            guard topics.contains(where: { $0.id == q.topicID }), materials.contains(where: { $0.id == q.materialID }), (2...8).contains(q.choices.count), q.choices.indices.contains(q.answer), Set(q.choices).count == q.choices.count else { throw Invalid.reference }
            for c in q.choices { try text(c, 2000) }
        }
        guard (0...10000).contains(examBlueprint.questionCount), (1...1440).contains(examBlueprint.minutes), (1...10000).contains(examBlueprint.points) else { throw Invalid.limit }
        if let equationSheet { guard materials.contains(where: { $0.id == equationSheet && Self.safePath($0.ref) && $0.ref.lowercased().hasSuffix(".pdf") }) else { throw Invalid.reference } }
    }
    public static func safePath(_ p: String) -> Bool {
        p.hasPrefix("attachments/") && !p.contains("\\") && !p.contains(":") && !p.contains("%") && p.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { !$0.isEmpty && $0 != ".." && $0 != "." }
    }
}

/// Atomic, immutable imports. Reimporting the same identity never overwrites learner work.
public enum CourseBundleImporter {
    public static func add(_ data: Data, to root: URL) throws -> CourseBundle {
        let bundle = try CourseBundle.decode(data)
        guard !bundle.materials.contains(where: { CourseBundle.safePath($0.ref) }) else { throw CourseBundle.Invalid.reference }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let target = root.appendingPathComponent(bundle.course.id + ".json")
        let stage = root.appendingPathComponent(".import-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: stage) }
        try data.write(to: stage, options: .withoutOverwriting)
        guard !FileManager.default.fileExists(atPath: root.appendingPathComponent(bundle.course.id).path) else { throw CourseBundle.Invalid.duplicate }
        try FileManager.default.moveItem(at: stage, to: target)
        return bundle
    }
}
