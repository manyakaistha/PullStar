import SwiftUI
import PullStarKit

/// Port of frontend/src/components/ParameterBays.tsx — the right-hand "Alignment setup" pane.
struct SetupPane: View {
    @Bindable var model: AppModel
    /// When true the pane scrolls internally and pins its footer (wide layout);
    /// otherwise its content flows in the page and the footer is provided separately.
    var scrollsInternally: Bool
    var onChooseInput: () -> Void
    var onChooseOutput: () -> Void
    var onChooseConversion: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            SetupTitle()
            if scrollsInternally {
                ScrollView { fields }
                    .scrollIndicators(.automatic)
                    .scrollDismissesKeyboard(.interactively)
                SetupFooter(model: model)
            } else {
                fields
            }
        }
        .glassSurface()
    }

    private var fields: some View {
        VStack(spacing: 0) {
            sourceSection
            alignmentSection
            outputSection
        }
        .disabled(model.isProcessing || model.isDetecting)
        .opacity(model.isProcessing || model.isDetecting ? 0.6 : 1)
    }

    // MARK: 01 Source frames

    private var sourceSection: some View {
        SetupSection(number: "01", title: "Source frames", description: "Choose the sequence you want to align.") {
            FieldLabel(text: "Image folder")
            FolderField(value: model.hasInputFolder ? model.config.inputDirectory.lastPathComponent : nil,
                        placeholder: "Choose your night-sky images",
                        accessibilityTitle: "Choose image folder",
                        action: onChooseInput)
            Button { model.scanDirectory() } label: {
                HStack(spacing: 8) {
                    if model.isScanning { ProgressView().controlSize(.small).tint(PS.textSecondary) }
                    else { Image(systemName: "arrow.up.right").font(.system(size: 13, weight: .semibold)) }
                    Text(model.isScanning ? "Loading sequence…" : "Load frames")
                }
            }
            .buttonStyle(TactileButtonStyle(kind: .secondary, fullWidth: true))
            .disabled(model.isScanning || !model.hasInputFolder)

            if let error = model.scanError {
                Text(error).font(PS.note).foregroundStyle(PS.danger).fixedSize(horizontal: false, vertical: true)
            }
            if !model.sequence.isEmpty {
                HStack(spacing: 8) {
                    StatusDot()
                    Text("\(model.sequence.count) frames loaded").foregroundStyle(Color(hex: 0xb3cbbb))
                    Spacer()
                    Text(model.gapCount > 0 ? "\(model.gapCount) gap\(model.gapCount == 1 ? "" : "s")" : "Ready").foregroundStyle(Color(hex: 0x9999a1))
                }
                .font(PS.label)
                .padding(.vertical, 2)
            }

            AdvancedDisclosure(title: "Sequence order") {
                HStack {
                    Text("Sort frames by").font(PS.body).foregroundStyle(PS.textBody)
                    Spacer()
                    SegmentedControl(selection: Binding(get: { model.config.sortByTime }, set: { model.setSortByTime($0) }),
                                     options: [(true, "Time"), (false, "Name")])
                        .frame(width: 170)
                }
            }
            AdvancedDisclosure(title: "Processing hardware") {
                FieldLabel(text: "Processing device")
                SelectField(title: "Processing device", selection: $model.config.computeBackend,
                            options: [(.auto, "Automatic · CPU + GPU"), (.cpu, "CPU only")])
                HelperNote(text: model.hardwareSummary)
                HelperNote(text: "Parallel work is limited by available cores and memory.")
            }
            if model.sequence.contains(where: \.isRaw) {
                AdvancedDisclosure(title: "High-noise RAW recovery") {
                    SettingToggle(label: "Recover faint and streaked stars",
                                  description: "Use sensor data for detection and reduce noise before stacking.",
                                  isOn: $model.config.rawNoiseReduction)
                    FieldLabel(text: "RAW exposure boost")
                    SelectField(title: "RAW exposure boost", selection: $model.config.rawExposureEV,
                                options: [(0.0, "Original exposure"), (1.0, "+1 stop"), (2.0, "+2 stops"), (3.0, "+3 stops")])
                    HelperNote(text: "Applies to the RAW stack. Source files stay unchanged.")
                }
            }
        }
    }

    // MARK: 02 Build your alignment

    private var alignmentSection: some View {
        SetupSection(number: "02", title: "Build your alignment", description: "Automatic by default. Manual references are optional.") {
            AdvancedDisclosure(title: "Manual reference tracking settings") {
                HelperNote(text: "These settings apply when you pick Polaris manually. Automatic field matching estimates camera motion directly.")
                SettingToggle(label: "Smooth star tracking", description: "Kalman filtering reduces frame-to-frame drift.",
                              isOn: $model.config.useKalman)
                SettingToggle(label: "Correct field rotation", description: "Pick a second reference star when enabled.",
                              isOn: $model.config.useRotation)
            }
            FieldLabel(text: "What would you like to create?").padding(.top, 4)
            SelectField(title: "What would you like to create?", selection: $model.exportMode,
                        options: [(.trails, "Star trails · image and optional video"),
                                  (.images, "Aligned images only · edit in another app")])
            HelperNote(text: model.exportMode == .images
                       ? "Correct camera wobble and export real exposures with a shared crop. Sky motion is preserved. No stacking, synthetic frames, or video rendering."
                       : "Align your exposures, then blend them into a star-trail image.")
            if model.exportMode == .trails {
                Rectangle().fill(Color.white.opacity(0.047)).frame(height: 1).padding(.vertical, 4)
                SettingSlider(label: "Trail extension", value: $model.config.extensionFactor, range: 1...5, step: 0.1, unit: "×",
                              helper: "1× preserves the original trail length.")
                SettingToggle(label: "Preserve the foreground", isOn: $model.config.useForegroundMask)
                SettingToggle(label: "Fill timeline gaps",
                              description: model.gapCount > 0 ? "\(model.gapCount) missing intervals detected." : "Interpolate missing exposure intervals.",
                              isOn: $model.config.fillGaps)
                AdvancedDisclosure(title: "Fine-tune trail synthesis") {
                    SettingSlider(label: "Tail taper", value: $model.config.tailTaperStrength, range: 0...1, step: 0.05,
                                  helper: "Fades synthetic trail brightness toward its far end.")
                    SettingSlider(label: "Tail angle cutoff", value: $model.config.tailAngleThreshold, range: 0...360, step: 1, unit: "°",
                                  helper: "0° keeps the full extension; otherwise it stops after this angle.")
                    SettingSlider(label: "Synthetic frames per exposure",
                                  value: Binding(get: { Double(model.config.ghostFramesPerReal) }, set: { model.config.ghostFramesPerReal = Int($0) }),
                                  range: 1...20)
                    SettingSlider(label: "Synthetic fade", value: $model.config.syntheticFadeFactor, range: 0...1, step: 0.05)
                }
            }
        }
    }

    // MARK: 03 Output

    private var outputSection: some View {
        SetupSection(number: "03", title: "Output", description: "Choose formats and a destination for your exports.", isLast: true) {
            AdvancedDisclosure(title: "Develop inputs before alignment") {
                FieldLabel(text: "Stacking input format")
                SelectField(title: "Stacking input format", selection: $model.config.conversionFormat,
                            options: [(.none, "Use original files"), (.jpg, "JPEG · smaller, 8-bit"), (.tiff, "TIFF · lossless, 16-bit")])
                if model.config.conversionFormat != .none {
                    VStack(alignment: .leading, spacing: 10) {
                        HelperNote(text: "Frames are converted once before alignment with your RAW exposure and noise settings."
                                   + (model.config.conversionFormat == .jpg ? " JPEG reduces precision and uses lossy compression." : " TIFF retains full precision and needs more disk space."))
                        FieldLabel(text: "Converted frame location")
                        FolderField(value: model.config.conversionOutputDirectory?.lastPathComponent,
                                    placeholder: "Temporary folder in source folder",
                                    accessibilityTitle: "Choose converted frame folder",
                                    action: onChooseConversion)
                        HelperNote(text: model.config.conversionOutputDirectory != nil
                                   ? "Converted files are kept in this location."
                                   : "Leave blank to use a temporary folder, removed on completion, cancellation, or error.")
                    }
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.black.opacity(0.2)))
                }
            }
            FieldLabel(text: "Image export format").padding(.top, 4)
            SelectField(title: "Image export format", selection: $model.imageFormat,
                        options: [(.tiff, "TIFF · lossless, source bit depth"), (.png, "PNG · lossless, source bit depth"), (.jpg, "JPEG · smaller, lossy 8-bit")])
            HelperNote(text: "TIFF and PNG retain 16-bit sources. JPEG is 8-bit at 95% quality. RAW files are developed, not exported as RAW.")

            FieldLabel(text: model.exportMode == .images ? "Output folder name" : "Output filename")
            InputField(placeholder: model.exportMode == .images ? "aligned_images" : "aligned_star_trails.tiff",
                       text: $model.config.outputBaseName)
            FieldLabel(text: "Save to")
            FolderField(value: model.config.outputDirectory.lastPathComponent,
                        placeholder: "On My iPad › PullStar",
                        accessibilityTitle: "Choose export folder",
                        action: onChooseOutput)

            FieldLabel(text: "Image export resolution")
            SelectField(title: "Image export resolution", selection: $model.config.imageResolution, options: Self.resolutions(sourceLabel: "Source resolution · maximum detail"))
            HelperNote(text: "Lower resolutions reduce processing time and file size. Image sequences are written to a new folder.")

            if model.exportMode == .trails {
                SettingToggle(label: "Also export aligned images",
                              description: "Save the real exposures in a separate folder beside the trail image.",
                              isOn: $model.config.saveFrames)
                SettingToggle(label: "Also create a trail-lapse video", isOn: $model.config.videoEnabled)
                if model.config.videoEnabled { videoOptions }
                AdvancedDisclosure(title: "Recovery options") {
                    SettingToggle(label: "Save recovery checkpoints", isOn: $model.config.useCheckpoint)
                    SettingToggle(label: "Resume from checkpoint", isOn: $model.config.resume)
                }
            }
        }
    }

    private var videoOptions: some View {
        VStack(alignment: .leading, spacing: 10) {
            FieldLabel(text: "Video file format")
            SelectField(title: "Video file format", selection: $model.videoFormat,
                        options: [(.mp4, "MP4 · broad playback support"), (.mov, "MOV · editing workflow")])
            FieldLabel(text: "Video quality")
            SelectField(title: "Video quality", selection: $model.videoQuality,
                        options: [(.high, "High quality · H.264"), (.hevc, "Efficient · HEVC"), (.prores, "ProRes 422 HQ"), (.lossless, "Lossless H.264"), (.medium, "Medium quality")])
            FieldLabel(text: "Video resolution")
            SelectField(title: "Video resolution", selection: $model.config.videoResolution, options: Self.resolutions(sourceLabel: "Source resolution"))
            HelperNote(text: "Video is never upscaled. Lower settings reduce video encoding time.")
            SegmentedControl(selection: $model.videoPlaybackMode, options: [(.slowmo, "Slow motion"), (.hyperlapse, "Hyperlapse")])
            if model.videoPlaybackMode == .slowmo {
                FieldLabel(text: "Slow-motion pace")
                SelectField(title: "Slow-motion pace", selection: $model.config.videoSlowdown,
                            options: [(1, "1× · Fast"), (2, "2× · Moderate"), (4, "4× · Slow"), (8, "8× · Very slow")])
                HelperNote(text: "Controls how many video snapshots are written per exposure interval. The final stack still uses every synthetic frame.")
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.black.opacity(0.2)))
    }

    static func resolutions(sourceLabel: String) -> [(Resolution, String)] {
        [(.source, sourceLabel), (.k4, "4K · up to 3840px"), (.k2, "2K · up to 2560px"), (.p1080, "1080p · up to 1920px"), (.p720, "720p · up to 1280px")]
    }
}

// MARK: - Pieces

private struct SetupTitle: View {
    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 6) {
                Eyebrow(text: "A GOOD STACK STARTS HERE")
                Text("Alignment setup").font(.system(size: 22, weight: .medium)).tracking(-0.6).foregroundStyle(Color(hex: 0xeeeeef))
            }
            Spacer()
            Image(systemName: "slider.horizontal.3").font(.system(size: 20, weight: .light)).foregroundStyle(Color(hex: 0x88888f))
        }
        .padding(.horizontal, 24).padding(.top, 24).padding(.bottom, 20)
        .overlay(alignment: .bottom) { Rectangle().fill(PS.line).frame(height: 1) }
    }
}

struct SetupSection<Content: View>: View {
    let number: String
    let title: String
    let description: String
    var isLast = false
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 13) {
                Text(number).font(.system(size: 12, weight: .medium).monospacedDigit()).foregroundStyle(Color(hex: 0xbdbdc4))
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(LinearGradient(colors: [Color.white.opacity(0.063), Color.white.opacity(0.012)], startPoint: .topLeading, endPoint: .bottomTrailing)))
                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.white.opacity(0.094)))
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.system(size: 16, weight: .medium)).foregroundStyle(PS.textPrimary)
                    Text(description).font(PS.note).foregroundStyle(PS.textMuted).fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.bottom, 20)
            VStack(alignment: .leading, spacing: 12) { content }
        }
        .padding(.horizontal, 24).padding(.vertical, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { if !isLast { Rectangle().fill(PS.line).frame(height: 1) } }
    }
}

/// `.setup-footer` — status line plus the primary start / cancel action.
struct SetupFooter: View {
    @Bindable var model: AppModel

    private var minimumFrames: Int { model.minimumFrames }
    private var nameMissing: Bool { model.config.outputBaseName.trimmingCharacters(in: .whitespaces).isEmpty }
    private var ready: Bool { model.hasInputFolder && model.isReady }

    private var message: String {
        if model.isCancelling { return "Stopping at the next processing boundary." }
        if model.isProcessing { return "You can cancel while frames and trails are being processed." }
        if model.isDetecting { return "Wait for detection, or cancel it in the image workspace." }
        if let error = model.validationError, !model.sequence.isEmpty { return error }
        if nameMissing && model.sequence.count >= minimumFrames { return "Enter an output name to continue." }
        if ready { return "Ready when you are. References can be detected automatically." }
        if !model.sequence.isEmpty && model.sequence.count < minimumFrames { return "Choose at least \(minimumFrames) frames for this alignment mode." }
        return "Load a sequence to begin."
    }

    private var actionTitle: String {
        if model.isCancelling { return "Cancelling…" }
        if model.isProcessing {
            switch model.jobState.stage {
            case .conversion: return "Cancel conversion"
            case .pass2: return model.exportMode == .images ? "Cancel image export" : "Cancel trail creation"
            case .videoRender: return "Cancel video render"
            default: return "Cancel alignment"
            }
        }
        return model.exportMode == .images ? "Align & export images" : "Create star trails"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(message).font(PS.note).foregroundStyle(Color(hex: 0xa2a2aa)).lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                model.isProcessing ? model.cancelJob() : model.startJob()
            } label: {
                HStack(spacing: 10) {
                    if model.isCancelling { ProgressView().controlSize(.small) }
                    else { Image(systemName: model.isProcessing ? "stop.fill" : "arrow.up.right").font(.system(size: 14, weight: .semibold)) }
                    Text(actionTitle).font(.system(size: 16, weight: .semibold))
                }
            }
            .buttonStyle(TactileButtonStyle(kind: model.isProcessing ? .cancel : .primary, height: 54, fullWidth: true))
            .disabled(model.isCancelling || (!model.isProcessing && (!ready || model.validationError != nil)))
            .keyboardShortcut(model.isProcessing ? "." : "r", modifiers: .command)
        }
        .padding(.horizontal, 24).padding(.top, 18).padding(.bottom, 22)
        .background(LinearGradient(colors: [Color(hex: 0x19191b), Color(hex: 0x141415)], startPoint: .top, endPoint: .bottom))
        .overlay(alignment: .top) { Rectangle().fill(PS.line).frame(height: 1) }
    }
}
