import SwiftUI
import PullStarKit

/// Main Viewfinder view embedding `ViewfinderContent` and binding to `AppModel`.
public struct ViewfinderView: View {
    @Bindable public var model: AppModel

    public init(model: AppModel) {
        self.model = model
    }

    public var body: some View {
        ViewfinderContent(
            sequence: model.sequence,
            selectedIndex: Binding(
                get: { model.selectedReferenceIndex },
                set: { model.selectedReferenceIndex = $0 }
            ),
            previewLoader: { url, maxDimension in
                try await model.loadPreview(for: url, maxDimension: maxDimension)
            },
            detectedStars: model.jobState.detection?.referenceStars ?? [],
            polaris: Binding(
                get: { model.config.polaris },
                set: { model.config.polaris = $0 }
            ),
            secondStar: Binding(
                get: { model.config.secondStar },
                set: { model.config.secondStar = $0 }
            ),
            manualReferenceMode: model.config.polaris != nil || model.config.secondStar != nil,
            livePreviewURL: model.jobState.livePreviewURL,
            isProcessing: model.isProcessing,
            detectConfidence: model.jobState.detection?.confidence,
            isDetecting: model.isDetecting,
            onBrowseFolder: {
                // Folder selection invoked from empty state
            },
            onAutoDetect: {
                model.detectStars()
            },
            onCancelDetect: {
                // Detection cancellation
            },
            onSetReferenceFrame: { index in
                model.pickReferenceStars(index: index)
            }
        )
    }
}
