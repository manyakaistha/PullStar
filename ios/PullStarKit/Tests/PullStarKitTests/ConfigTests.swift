import Testing
import Foundation
@testable import PullStarKit

@Test func noStackRequiresSaveFrames() {
    var c = JobConfig(inputDirectory: URL(filePath: "/tmp"), outputDirectory: URL(filePath: "/tmp"))
    c.noStack = true
    #expect(c.validationError() != nil)
    c.saveFrames = true
    #expect(c.validationError() == nil)
}
