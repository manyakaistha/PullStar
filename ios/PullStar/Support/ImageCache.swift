import SwiftUI
import UIKit

/// High-performance in-memory thumbnail and preview cache for the filmstrip and viewfinder.
public actor ImageCache {
    public static let shared = ImageCache()

    private let cache = NSCache<NSURL, UIImage>()

    public init() {
        cache.countLimit = 250
        cache.totalCostLimit = 128 * 1024 * 1024 // 128 MB
    }

    public func image(for url: URL, maxDimension: Int) -> UIImage? {
        let key = cacheKey(url: url, maxDimension: maxDimension)
        return cache.object(forKey: key)
    }

    public func insert(_ image: UIImage, for url: URL, maxDimension: Int) {
        let key = cacheKey(url: url, maxDimension: maxDimension)
        let cost = Int(image.size.width * image.size.height * 4)
        cache.setObject(image, forKey: key, cost: cost)
    }

    public func remove(for url: URL, maxDimension: Int) {
        let key = cacheKey(url: url, maxDimension: maxDimension)
        cache.removeObject(forKey: key)
    }

    public func clear() {
        cache.removeAllObjects()
    }

    private func cacheKey(url: URL, maxDimension: Int) -> NSURL {
        let pathWithDim = "\(url.standardizedFileURL.path)?size=\(maxDimension)"
        return NSURL(fileURLWithPath: pathWithDim)
    }
}
