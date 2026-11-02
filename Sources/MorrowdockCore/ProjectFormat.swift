import Foundation

public struct ProjectStage: Codable, Identifiable, Sendable {
    public struct Check: Codable, Sendable { public let name, source: String }
    public let id, title, goal, lessonRef, lesson, language, workedExample, guidedPrompt: String
    public let concepts, walkthrough: [String]
    public let requiresHostProcess: Bool?
    public let starterFiles, referenceFiles: [String: String]
    public let visibleTests, hiddenTests: [Check]
    public let hints, reviewRubric: [String]
}
