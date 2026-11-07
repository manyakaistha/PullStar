import Testing
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
@testable import PullStarKit

struct IOTests {

    // Helper to create a temporary test directory
    private func createTempDirectory() throws -> URL {
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("pullstar_io_test_\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempURL, withIntermediateDirectories: true)
        return tempURL
    }

    // Helper to clean up a temporary directory
    private func cleanupDirectory(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    // Helper to create a synthetic PixelImage
    private func makeSyntheticImage(width: Int, height: Int, channels: Int) -> PixelImage {
        var data = [Float](repeating: 0, count: width * height * channels)
        for y in 0..<height {
            for x in 0..<width {
                let normX = Float(x) / Float(max(1, width - 1))
                let normY = Float(y) / Float(max(1, height - 1))
                let idx = (y * width + x) * channels
                if channels == 1 {
                    data[idx] = (normX + normY) * 0.5
                } else {
                    data[idx + 0] = normX            // Red
                    data[idx + 1] = normY            // Green
                    data[idx + 2] = 1.0 - normX      // Blue
                }
            }
        }
        return PixelImage(width: width, height: height, channels: channels, data: data)
    }

    // MARK: - 1. SequenceLister Tests

    @Test func sequenceListerNonExistentDirectoryThrows() {
        let fakeURL = URL(fileURLWithPath: "/non/existent/path/\(UUID().uuidString)")
        #expect(throws: IOError.self) {
            _ = try SequenceLister.listSequence(in: fakeURL)
        }
    }

    @Test func sequenceListerEmptyDirectoryReturnsEmpty() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let sequence = try SequenceLister.listSequence(in: tempDir)
        #expect(sequence.isEmpty)
    }

    @Test func sequenceListerSkipsPreviousResultsAndLivePreviews() throws {
        let dir = try createTempDirectory()
        defer { cleanupDirectory(dir) }
        let frame = makeSyntheticImage(width: 40, height: 30, channels: 3)
        for i in 0..<4 {
            try ImageWriter.write(frame, to: dir.appendingPathComponent("IMG_\(i).png"), format: .png)
        }
        // A previous run's cropped trail image and its live preview, saved into the source folder.
        try ImageWriter.write(makeSyntheticImage(width: 36, height: 26, channels: 3),
                              to: dir.appendingPathComponent("aligned_star_trails.tiff"), format: .tiff)
        try ImageWriter.write(frame, to: dir.appendingPathComponent("aligned_star_trails.tiff.live.jpg"), format: .jpg)

        let sequence = try SequenceLister.listSequence(in: dir, sortByTime: false)
        #expect(sequence.map(\.name) == ["IMG_0.png", "IMG_1.png", "IMG_2.png", "IMG_3.png"])
    }

    @Test func sequenceListerEnumerationAndSorting() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let baseDate = Date(timeIntervalSince1970: 1700000000)

        // Write 3 synthetic images with distinct names and dates
        let file1 = tempDir.appendingPathComponent("img_002.jpg")
        let file2 = tempDir.appendingPathComponent("img_001.jpg")
        let file3 = tempDir.appendingPathComponent("img_010.jpg")

        let img1 = makeSyntheticImage(width: 32, height: 24, channels: 3)
        try ImageWriter.writeJPEG(img1, to: file1)
        try ImageWriter.writeJPEG(img1, to: file2)
        try ImageWriter.writeJPEG(img1, to: file3)

        // Set different modification dates: file1 oldest, file3 middle, file2 newest
        let date1 = baseDate.addingTimeInterval(10)
        let date2 = baseDate.addingTimeInterval(30)
        let date3 = baseDate.addingTimeInterval(20)

        try FileManager.default.setAttributes([.modificationDate: date1], ofItemAtPath: file1.path)
        try FileManager.default.setAttributes([.modificationDate: date2], ofItemAtPath: file2.path)
        try FileManager.default.setAttributes([.modificationDate: date3], ofItemAtPath: file3.path)

        // Add a hidden file and a live preview file to verify they are skipped
        let hiddenFile = tempDir.appendingPathComponent(".hidden.jpg")
        try ImageWriter.writeJPEG(img1, to: hiddenFile)
        let liveFile = tempDir.appendingPathComponent("frame.live.jpg")
        try ImageWriter.writeJPEG(img1, to: liveFile)

        // Test sort by name (natural sort)
        let byName = try SequenceLister.listSequence(in: tempDir, sortByTime: false)
        #expect(byName.count == 3)
        #expect(byName[0].name == "img_001.jpg")
        #expect(byName[1].name == "img_002.jpg")
        #expect(byName[2].name == "img_010.jpg")
        #expect(byName[0].width == 32)
        #expect(byName[0].height == 24)
        #expect(!byName[0].isRaw)

        // Test sort by time
        let byTime = try SequenceLister.listSequence(in: tempDir, sortByTime: true)
        #expect(byTime.count == 3)
        #expect(byTime[0].name == "img_002.jpg")
        #expect(byTime[1].name == "img_010.jpg")
        #expect(byTime[2].name == "img_001.jpg")
    }

    @Test func sequenceListerRecognizesRawExtensions() {
        #expect(SequenceLister.isRaw(url: URL(fileURLWithPath: "test.dng")))
        #expect(SequenceLister.isRaw(url: URL(fileURLWithPath: "test.CR2")))
        #expect(SequenceLister.isRaw(url: URL(fileURLWithPath: "test.NEF")))
        #expect(SequenceLister.isRaw(url: URL(fileURLWithPath: "test.arw")))
        #expect(!SequenceLister.isRaw(url: URL(fileURLWithPath: "test.jpg")))
        #expect(!SequenceLister.isRaw(url: URL(fileURLWithPath: "test.tiff")))
        #expect(!SequenceLister.isRaw(url: URL(fileURLWithPath: "test.png")))
    }

    // MARK: - 2. ImageWriter & ImageDecoder Round-Trip Tests

    @Test func tiff16BitRoundTrip() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let fileURL = tempDir.appendingPathComponent("test16.tiff")
        let original = makeSyntheticImage(width: 8, height: 6, channels: 3)

        try ImageWriter.writeTIFF(original, to: fileURL, colorSpace: .sRGB)
        #expect(FileManager.default.fileExists(atPath: fileURL.path))

        let decoded = try ImageDecoder.decode(from: fileURL)
        #expect(decoded.width == original.width)
        #expect(decoded.height == original.height)
        #expect(decoded.channels == 3)

        // Verify precision: values should match very closely
        for i in 0..<original.data.count {
            let diff = abs(decoded.data[i] - original.data[i])
            #expect(diff < 0.05, "Mismatch at index \(i): original \(original.data[i]), decoded \(decoded.data[i])")
        }
    }

    @Test func png16BitRoundTrip() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let fileURL = tempDir.appendingPathComponent("test16.png")
        let original = makeSyntheticImage(width: 10, height: 10, channels: 3)

        try ImageWriter.writePNG(original, to: fileURL, colorSpace: .sRGB)
        #expect(FileManager.default.fileExists(atPath: fileURL.path))

        let decoded = try ImageDecoder.decode(from: fileURL)
        #expect(decoded.width == original.width)
        #expect(decoded.height == original.height)
        #expect(decoded.channels == 3)
    }

    @Test func jpeg8BitRoundTrip() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let fileURL = tempDir.appendingPathComponent("test8.jpg")
        let original = makeSyntheticImage(width: 16, height: 16, channels: 3)

        try ImageWriter.writeJPEG(original, to: fileURL, quality: 0.95, colorSpace: .sRGB)
        #expect(FileManager.default.fileExists(atPath: fileURL.path))

        let decoded = try ImageDecoder.decode(from: fileURL)
        #expect(decoded.width == original.width)
        #expect(decoded.height == original.height)
        #expect(decoded.channels == 3)
    }

    @Test func writeToDataInMemory() throws {
        let image = makeSyntheticImage(width: 12, height: 8, channels: 3)
        let tiffData = try ImageWriter.writeToData(image, format: .tiff)
        #expect(tiffData.count > 0)

        let pngData = try ImageWriter.writeToData(image, format: .png)
        #expect(pngData.count > 0)

        let jpgData = try ImageWriter.writeToData(image, format: .jpg, quality: 0.95)
        #expect(jpgData.count > 0)
    }

    // MARK: - 3. decodeLuma and Downscale Tests

    @Test func decodeLumaGeneratesSingleChannel() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let fileURL = tempDir.appendingPathComponent("luma_test.jpg")
        let original = makeSyntheticImage(width: 20, height: 15, channels: 3)
        try ImageWriter.writeJPEG(original, to: fileURL)

        let luma = try ImageDecoder.decodeLuma(from: fileURL)
        #expect(luma.width == 20)
        #expect(luma.height == 15)
        #expect(luma.channels == 1)
        #expect(luma.data.count == 20 * 15)

        // Verify with maxDimension constraint
        let constrainedLuma = try ImageDecoder.decodeLuma(from: fileURL, maxDimension: 10)
        #expect(max(constrainedLuma.width, constrainedLuma.height) <= 10)
        #expect(constrainedLuma.channels == 1)
    }

    @Test func downscaleHelperPreservesAspectRatio() {
        // 3-channel test
        let img3 = makeSyntheticImage(width: 200, height: 100, channels: 3)
        let scaled3 = ImageDecoder.downscale(img3, maxDimension: 50)
        #expect(scaled3.width == 50)
        #expect(scaled3.height == 25)
        #expect(scaled3.channels == 3)
        #expect(scaled3.data.count == 50 * 25 * 3)

        // 1-channel test
        let img1 = makeSyntheticImage(width: 100, height: 300, channels: 1)
        let scaled1 = img1.downscaled(maxDimension: 60)
        #expect(scaled1.width == 20)
        #expect(scaled1.height == 60)
        #expect(scaled1.channels == 1)
        #expect(scaled1.data.count == 20 * 60)

        // Unchanged when maxDimension is larger
        let noOp = img3.downscaled(maxDimension: 500)
        #expect(noOp.width == 200)
        #expect(noOp.height == 100)
    }

    // MARK: - 4. PreviewRenderer Tests

    @Test func previewRendererProducesValidJPEG() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let fileURL = tempDir.appendingPathComponent("preview_src.png")
        let original = makeSyntheticImage(width: 300, height: 200, channels: 3)
        try ImageWriter.writePNG(original, to: fileURL)

        let jpegData = try PreviewRenderer.renderPreview(of: fileURL, maxDimension: 80)
        #expect(jpegData.count > 0)

        // Verify the rendered JPEG data can be inspected and fits max dimension
        guard let source = CGImageSourceCreateWithData(jpegData as CFData, nil) else {
            Issue.record("Preview data could not be parsed as CGImageSource")
            return
        }
        guard let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] else {
            Issue.record("No properties in preview JPEG")
            return
        }
        let w = props[kCGImagePropertyPixelWidth] as? Int ?? 0
        let h = props[kCGImagePropertyPixelHeight] as? Int ?? 0
        #expect(max(w, h) <= 80)
    }

    // MARK: - 5. convertInputs Tests

    @Test func convertInputsToJPEGAndManifestExclusion() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let inputDir = tempDir.appendingPathComponent("inputs")
        let outputDir = tempDir.appendingPathComponent("converted")
        try FileManager.default.createDirectory(at: inputDir, withIntermediateDirectories: true)

        let img = makeSyntheticImage(width: 24, height: 16, channels: 3)
        let src1 = inputDir.appendingPathComponent("photo_a.png")
        let src2 = inputDir.appendingPathComponent("photo_b.png")
        try ImageWriter.writePNG(img, to: src1)
        try ImageWriter.writePNG(img, to: src2)

        var config = JobConfig(inputDirectory: inputDir, outputDirectory: tempDir)
        config.conversionFormat = .jpg
        config.conversionOutputDirectory = outputDir

        var progressCalls: [Double] = []
        let converted = try ImageWriter.convertInputs(
            sources: [src1, src2],
            config: config
        ) { progress, current, total in
            progressCalls.append(progress)
        }

        #expect(converted.count == 2)
        #expect(progressCalls.count >= 2)
        #expect(FileManager.default.fileExists(atPath: converted[0].path))
        #expect(FileManager.default.fileExists(atPath: converted[1].path))

        // Manifest check
        let manifestURL = outputDir.appendingPathComponent(".staraligner-conversion.json")
        #expect(FileManager.default.fileExists(atPath: manifestURL.path))

        // SequenceLister artifact exclusion check:
        // If we list the outputDir, the converted files in it should be excluded per manifest!
        let seq = try SequenceLister.listSequence(in: outputDir)
        #expect(seq.isEmpty, "SequenceLister should exclude files listed in .staraligner-conversion.json")
    }

    @Test func convertInputsNoneReturnsOriginals() throws {
        let tempDir = try createTempDirectory()
        defer { cleanupDirectory(tempDir) }

        let src1 = tempDir.appendingPathComponent("src.jpg")
        let img = makeSyntheticImage(width: 8, height: 8, channels: 3)
        try ImageWriter.writeJPEG(img, to: src1)

        let config = JobConfig(inputDirectory: tempDir, outputDirectory: tempDir)
        #expect(config.conversionFormat == .none)

        let result = try ImageWriter.convertInputs(sources: [src1], config: config)
        #expect(result == [src1])
    }
}
