import Photos
import UIKit

/// Helper for saving aligned images and video files to the user's Photos library (Add-Only permission).
@MainActor
public final class PhotoSaver: NSObject, ObservableObject {
    public static let shared = PhotoSaver()

    @Published public var isSaving = false
    @Published public var successMessage: String?
    @Published public var errorMessage: String?

    public func saveImage(at url: URL) async {
        guard let image = UIImage(contentsOfFile: url.path) else {
            self.errorMessage = "Could not load image at path."
            return
        }
        await saveImage(image)
    }

    public func saveImage(_ image: UIImage) async {
        isSaving = true
        defer { isSaving = false }

        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            self.errorMessage = "Photo library access not granted. Please enable in Settings."
            return
        }

        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.creationRequestForAsset(from: image)
            }
            self.successMessage = "Saved to Photos"
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }

    public func saveVideo(at url: URL) async {
        isSaving = true
        defer { isSaving = false }

        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            self.errorMessage = "Photo library access not granted. Please enable in Settings."
            return
        }

        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: url)
            }
            self.successMessage = "Video saved to Photos"
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }

    public func dismissNotice() {
        successMessage = nil
        errorMessage = nil
    }
}
