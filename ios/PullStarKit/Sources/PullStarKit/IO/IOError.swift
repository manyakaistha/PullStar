import Foundation

public enum IOError: Error, LocalizedError, Sendable, Equatable {
    case folderNotFound(URL)
    case notADirectory(URL)
    case fileNotFound(URL)
    case noSupportedImagesFound(URL)
    case cannotDecodeImage(URL, reason: String)
    case cannotEncodeImage(reason: String)
    case cannotWriteFile(URL, reason: String)
    case unsupportedFormat(String)

    public var errorDescription: String? {
        switch self {
        case .folderNotFound(let url):
            return "Folder not found: \(url.path)"
        case .notADirectory(let url):
            return "Path is not a directory: \(url.path)"
        case .fileNotFound(let url):
            return "File not found: \(url.path)"
        case .noSupportedImagesFound(let url):
            return "No supported image files found in: \(url.path)"
        case .cannotDecodeImage(let url, let reason):
            return "Cannot decode image \(url.lastPathComponent): \(reason)"
        case .cannotEncodeImage(let reason):
            return "Cannot encode image: \(reason)"
        case .cannotWriteFile(let url, let reason):
            return "Cannot write file \(url.lastPathComponent): \(reason)"
        case .unsupportedFormat(let format):
            return "Unsupported format: \(format)"
        }
    }
}
