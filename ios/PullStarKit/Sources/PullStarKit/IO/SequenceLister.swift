import Foundation
import ImageIO

public enum SequenceLister: Sendable {
    public static let standardExtensions: Set<String> = [
        "jpg", "jpeg", "png", "tif", "tiff", "heic"
    ]

    public static let rawExtensions: Set<String> = [
        "dng", "cr2", "cr3", "nef", "arw", "raf", "orf", "rw2", "pef", "srw", "raw"
    ]

    public static var supportedExtensions: Set<String> {
        standardExtensions.union(rawExtensions)
    }

    public static func isRaw(url: URL) -> Bool {
        rawExtensions.contains(url.pathExtension.lowercased())
    }

    public static func isSupported(url: URL) -> Bool {
        supportedExtensions.contains(url.pathExtension.lowercased())
    }

    /// Enumerate supported images in a folder, returning metadata sorted per `sortByTime`.
    public static func listSequence(in folder: URL, sortByTime: Bool = true) throws -> [SequenceInfo] {
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: folder.path, isDirectory: &isDir) else {
            throw IOError.folderNotFound(folder)
        }
        guard isDir.boolValue else {
            throw IOError.notADirectory(folder)
        }

        let folderSecurityAccessed = folder.startAccessingSecurityScopedResource()
        defer {
            if folderSecurityAccessed {
                folder.stopAccessingSecurityScopedResource()
            }
        }

        // Check for conversion manifest to exclude artifacts from prior conversion runs
        let excludedFilenames = loadExcludedArtifacts(in: folder)

        let resourceKeys: Set<URLResourceKey> = [
            .isRegularFileKey,
            .creationDateKey,
            .contentModificationDateKey,
            .isHiddenKey
        ]

        let fileURLs: [URL]
        do {
            fileURLs = try FileManager.default.contentsOfDirectory(
                at: folder,
                includingPropertiesForKeys: Array(resourceKeys),
                options: [.skipsHiddenFiles]
            )
        } catch {
            throw IOError.cannotWriteFile(folder, reason: "Cannot read directory contents: \(error.localizedDescription)")
        }

        var sequence: [SequenceInfo] = []

        for fileURL in fileURLs {
            let filename = fileURL.lastPathComponent

            // Skip hidden files, live preview files, and manifest artifacts
            if filename.hasPrefix(".") || filename.hasSuffix(".live.jpg") {
                continue
            }
            if excludedFilenames.contains(filename) || excludedFilenames.contains(fileURL.path) {
                continue
            }

            let ext = fileURL.pathExtension.lowercased()
            guard supportedExtensions.contains(ext) else {
                continue
            }

            var isRegularFile = false
            if let values = try? fileURL.resourceValues(forKeys: [.isRegularFileKey]),
               values.isRegularFile == true {
                isRegularFile = true
            } else if (try? fileURL.checkResourceIsReachable()) == true {
                isRegularFile = true
            }
            guard isRegularFile else { continue }

            let fileSecurityAccessed = fileURL.startAccessingSecurityScopedResource()
            defer {
                if fileSecurityAccessed {
                    fileURL.stopAccessingSecurityScopedResource()
                }
            }

            var info = SequenceInfo(url: fileURL, name: filename)
            info.isRaw = rawExtensions.contains(ext)

            // Extract EXIF date & pixel dimensions via ImageIO
            if let source = CGImageSourceCreateWithURL(fileURL as CFURL, nil) {
                if let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] {
                    // Dimensions with orientation handling
                    let rawWidth = properties[kCGImagePropertyPixelWidth] as? Int ?? 0
                    let rawHeight = properties[kCGImagePropertyPixelHeight] as? Int ?? 0
                    let orientation = properties[kCGImagePropertyOrientation] as? Int ?? 1

                    if orientation >= 5 && orientation <= 8 {
                        info.width = rawHeight
                        info.height = rawWidth
                    } else {
                        info.width = rawWidth
                        info.height = rawHeight
                    }

                    // EXIF date
                    info.captureDate = extractCaptureDate(from: properties)
                }
            }

            // Fallback to file creation / modification date if EXIF missing
            if info.captureDate == nil {
                if let values = try? fileURL.resourceValues(forKeys: [.creationDateKey, .contentModificationDateKey]) {
                    info.captureDate = values.creationDate ?? values.contentModificationDate
                }
            }

            sequence.append(info)
        }

        // Sort sequence
        if sortByTime {
            sequence.sort { a, b in
                let da = a.captureDate ?? Date.distantPast
                let db = b.captureDate ?? Date.distantPast
                if da != db {
                    return da < db
                }
                return a.name.localizedStandardCompare(b.name) == .orderedAscending
            }
        } else {
            sequence.sort { a, b in
                a.name.localizedStandardCompare(b.name) == .orderedAscending
            }
        }

        return sequence
    }

    /// Asynchronous wrapper for `listSequence`.
    public static func listSequence(in folder: URL, sortByTime: Bool = true) async throws -> [SequenceInfo] {
        let syncFunc: (URL, Bool) throws -> [SequenceInfo] = listSequence(in:sortByTime:)
        return try syncFunc(folder, sortByTime)
    }

    // MARK: - Internal Helpers

    private static func loadExcludedArtifacts(in folder: URL) -> Set<String> {
        var excluded = Set<String>()
        let manifestURL = folder.appendingPathComponent(".staraligner-conversion.json")
        guard let data = try? Data(contentsOf: manifestURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return excluded
        }

        if let generated = json["generated_files"] as? [String] {
            for item in generated {
                let url = URL(fileURLWithPath: item)
                excluded.insert(url.lastPathComponent)
                excluded.insert(url.path)
            }
        }

        if let frames = json["frames"] as? [[String: Any]] {
            for frame in frames {
                if let converted = frame["converted"] as? String {
                    let url = URL(fileURLWithPath: converted)
                    excluded.insert(url.lastPathComponent)
                    excluded.insert(url.path)
                }
            }
        }

        return excluded
    }

    private static func extractCaptureDate(from properties: [CFString: Any]) -> Date? {
        if let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] {
            if let dateString = exif[kCGImagePropertyExifDateTimeOriginal] as? String,
               let date = parseExifDate(dateString) {
                return date
            }
            if let dateString = exif[kCGImagePropertyExifDateTimeDigitized] as? String,
               let date = parseExifDate(dateString) {
                return date
            }
        }

        if let tiff = properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any] {
            if let dateString = tiff[kCGImagePropertyTIFFDateTime] as? String,
               let date = parseExifDate(dateString) {
                return date
            }
        }

        return nil
    }

    private static func parseExifDate(_ string: String) -> Date? {
        let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let formatter1 = DateFormatter()
        formatter1.locale = Locale(identifier: "en_US_POSIX")
        formatter1.timeZone = TimeZone(secondsFromGMT: 0)
        formatter1.dateFormat = "yyyy:MM:dd HH:mm:ss"
        if let date = formatter1.date(from: trimmed) {
            return date
        }

        let formatter2 = DateFormatter()
        formatter2.locale = Locale(identifier: "en_US_POSIX")
        formatter2.timeZone = TimeZone(secondsFromGMT: 0)
        formatter2.dateFormat = "yyyy-MM-dd HH:mm:ss"
        if let date = formatter2.date(from: trimmed) {
            return date
        }

        let iso = ISO8601DateFormatter()
        if let date = iso.date(from: trimmed) {
            return date
        }

        return nil
    }
}
