import SwiftUI
import PullStarKit

public struct SetupView: View {
    @Bindable public var model: AppModel

    @State private var showingInputPicker = false
    @State private var showingOutputPicker = false
    @State private var showingConversionPicker = false

    public init(model: AppModel) {
        self.model = model
    }

    public var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("A GOOD STACK STARTS HERE")
                        .font(.psEyebrow)
                        .foregroundColor(.psTextMuted)
                        .tracking(1.4)
                    Text("Alignment setup")
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(.psTextPrimary)
                }
                Spacer()
                Image(systemName: "slider.horizontal.3")
                    .font(.system(size: 18, weight: .light))
                    .foregroundColor(.psTextMuted)
            }
            .padding(.horizontal, 22)
            .padding(.top, 24)
            .padding(.bottom, 18)
            .overlay(alignment: .bottom) {
                Divider().background(Color.white.opacity(0.1))
            }

            // Scrollable parameters
            ScrollView(.vertical, showsIndicators: true) {
                VStack(spacing: 0) {
                    sourceFramesSection
                    buildAlignmentSection
                    outputSection
                }
                .disabled(model.isProcessing || model.isDetecting)
                .opacity((model.isProcessing || model.isDetecting) ? 0.6 : 1.0)
            }

            // Footer
            setupFooter
        }
        .background(Color.psSurfaceSolid)
        .fileImporter(
            isPresented: $showingInputPicker,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                model.chooseFolder(url)
            }
        }
        .fileImporter(
            isPresented: $showingOutputPicker,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                model.chooseOutputFolder(url)
            }
        }
        .fileImporter(
            isPresented: $showingConversionPicker,
            allowedContentTypes: [.folder],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                model.chooseConversionFolder(url)
            }
        }
    }

    // MARK: - Section 01: Source frames
    private var sourceFramesSection: some View {
        SetupSectionView(
            number: "01",
            title: "Source frames",
            description: "Choose the sequence you want to align."
        ) {
            Text("Image folder")
                .font(.psFieldLabel)
                .foregroundColor(.psTextSecondary)

            HStack(spacing: 8) {
                TextField("/path/to/your/night-sky-images", text: Binding(
                    get: { model.config.inputDirectory.path },
                    set: { model.config.inputDirectory = URL(fileURLWithPath: $0) }
                ))
                .font(.psFieldInput)
                .foregroundColor(.psTextPrimary)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.psFieldInputBg)
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(Color.white.opacity(0.12), lineWidth: 1)
                        )
                )

                Button {
                    showingInputPicker = true
                } label: {
                    Image(systemName: "folder")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(.psTextPrimary)
                        .frame(width: 42, height: 42)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color.white.opacity(0.08))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(Color.white.opacity(0.15), lineWidth: 1)
                                )
                        )
                }
                .accessibilityLabel("Choose image folder")
            }

            PSButton(
                model.isScanning ? "Loading sequence…" : "Load frames",
                systemImage: model.isScanning ? nil : "arrow.up.right",
                variant: .secondary,
                isLoading: model.isScanning
            ) {
                model.scanDirectory()
            }
            .disabled(model.isScanning || model.config.inputDirectory.path.isEmpty)

            if let error = model.scanError {
                Text(error)
                    .font(.system(size: 11, weight: .regular))
                    .foregroundColor(.psDanger)
            }

            if !model.sequence.isEmpty {
                HStack(spacing: 8) {
                    LEDIndicator(color: .emerald, size: 6)
                    Text("\(model.sequence.count) frames loaded")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color(hex: 0xb3cbbb))
                    Spacer()
                    Text(model.gapCount > 0 ? "\(model.gapCount) gaps" : "Ready")
                        .font(.system(size: 11, weight: .regular))
                        .foregroundColor(.psTextMuted)
                }
                .padding(.vertical, 2)
            }

            AdvancedDisclosure("Sequence order") {
                HStack {
                    Text("Sort frames by")
                        .font(.system(size: 11, weight: .regular))
                        .foregroundColor(.psTextSecondary)
                    Spacer()
                    Picker("Sequence sort mode", selection: $model.config.sortByTime) {
                        Text("Time").tag(true)
                        Text("Name").tag(false)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 140)
                    .onChange(of: model.config.sortByTime) { _, _ in
                        model.scanDirectory()
                    }
                }
            }

            AdvancedDisclosure("Processing hardware") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Processing device")
                        .font(.psFieldLabel)
                        .foregroundColor(.psTextSecondary)

                    Picker("Processing device", selection: $model.config.computeBackend) {
                        Text("Automatic · CPU + supported GPU").tag(ComputeBackend.auto)
                        Text("CPU only").tag(ComputeBackend.cpu)
                    }
                    .pickerStyle(.menu)
                    .tint(.psTextPrimary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Color.psFieldInputBg)
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                    )

                    Text(model.hardwareSummary)
                        .font(.psHardwareNote)
                        .foregroundColor(.psTextMuted)
                    Text("Parallel work is limited by available cores and memory.")
                        .font(.psHardwareNote)
                        .foregroundColor(.psTextMuted)
                }
            }

            if model.sequence.contains(where: { $0.isRaw }) {
                AdvancedDisclosure("High-noise RAW recovery") {
                    VStack(alignment: .leading, spacing: 10) {
                        PSToggle(
                            "Recover faint and streaked stars",
                            isOn: $model.config.rawNoiseReduction,
                            description: "Use sensor data for detection and reduce noise before stacking."
                        )

                        Text("RAW exposure boost")
                            .font(.psFieldLabel)
                            .foregroundColor(.psTextSecondary)

                        Picker("RAW exposure boost", selection: $model.config.rawExposureEV) {
                            Text("Original exposure").tag(0.0)
                            Text("+1 stop").tag(1.0)
                            Text("+2 stops").tag(2.0)
                            Text("+3 stops").tag(3.0)
                        }
                        .pickerStyle(.menu)
                        .tint(.psTextPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color.psFieldInputBg)
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                        )

                        Text("Applies to the RAW stack. Source files stay unchanged.")
                            .font(.psHardwareNote)
                            .foregroundColor(.psTextMuted)
                    }
                }
            }
        }
    }

    // MARK: - Section 02: Build your alignment
    private var buildAlignmentSection: some View {
        SetupSectionView(
            number: "02",
            title: "Build your alignment",
            description: "Automatic by default. Manual references are optional."
        ) {
            AdvancedDisclosure("Manual reference tracking settings") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("These settings apply when you pick Polaris manually. Automatic field matching estimates camera motion directly.")
                        .font(.psHardwareNote)
                        .foregroundColor(.psTextMuted)

                    PSToggle(
                        "Smooth star tracking",
                        isOn: $model.config.useKalman,
                        description: "Kalman filtering reduces frame-to-frame drift."
                    )

                    PSToggle(
                        "Correct field rotation",
                        isOn: $model.config.useRotation,
                        description: "Pick a second reference star when enabled."
                    )
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("What would you like to create?")
                    .font(.psFieldLabel)
                    .foregroundColor(.psTextSecondary)

                Picker("Export Mode", selection: Binding(
                    get: { model.exportMode },
                    set: { model.exportMode = $0 }
                )) {
                    Text("Star trails · image and optional video").tag(ExportMode.trails)
                    Text("Aligned images only · edit in another app").tag(ExportMode.images)
                }
                .pickerStyle(.menu)
                .tint(.psTextPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.psFieldInputBg)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                )

                Text(model.exportMode == .images
                    ? "Correct camera wobble and export real exposures with a shared crop. Sky motion is preserved. No stacking, synthetic frames, or video rendering."
                    : "Align your exposures, then blend them into a star-trail image."
                )
                .font(.psHardwareNote)
                .foregroundColor(.psTextMuted)
            }

            if model.exportMode == .trails {
                Divider().background(Color.white.opacity(0.08))

                PSSlider(
                    "Trail extension",
                    value: $model.config.extensionFactor,
                    in: 1.0...5.0,
                    step: 0.1,
                    unit: "×",
                    helperText: "1× preserves the original trail length."
                )

                PSToggle(
                    "Preserve the foreground",
                    isOn: $model.config.useForegroundMask
                )

                PSToggle(
                    "Fill timeline gaps",
                    isOn: $model.config.fillGaps,
                    description: model.gapCount > 0
                        ? "\(model.gapCount) missing intervals detected."
                        : "Interpolate missing exposure intervals."
                )

                AdvancedDisclosure("Fine-tune trail synthesis") {
                    VStack(alignment: .leading, spacing: 12) {
                        PSSlider(
                            "Tail taper",
                            value: $model.config.tailTaperStrength,
                            in: 0.0...1.0,
                            step: 0.05,
                            helperText: "Fades synthetic trail brightness toward its far end."
                        )

                        PSSlider(
                            "Tail angle cutoff",
                            value: $model.config.tailAngleThreshold,
                            in: 0.0...360.0,
                            step: 1.0,
                            unit: "°",
                            helperText: "0° keeps the full extension; otherwise it stops after this angle."
                        )

                        PSSlider(
                            "Synthetic frames per exposure",
                            value: Binding(
                                get: { Double(model.config.ghostFramesPerReal) },
                                set: { model.config.ghostFramesPerReal = Int($0) }
                            ),
                            in: 1.0...20.0,
                            step: 1.0
                        )

                        PSSlider(
                            "Synthetic fade",
                            value: $model.config.syntheticFadeFactor,
                            in: 0.0...1.0,
                            step: 0.05
                        )
                    }
                }
            }
        }
    }

    // MARK: - Section 03: Output
    private var outputSection: some View {
        SetupSectionView(
            number: "03",
            title: "Output",
            description: "Choose formats and a destination for your exports."
        ) {
            AdvancedDisclosure("Develop inputs before alignment") {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Stacking input format")
                        .font(.psFieldLabel)
                        .foregroundColor(.psTextSecondary)

                    Picker("Stacking input format", selection: $model.config.conversionFormat) {
                        Text("Use original files").tag(ConversionFormat.none)
                        Text("JPEG · smaller, 8-bit").tag(ConversionFormat.jpg)
                        Text("TIFF · lossless, 16-bit").tag(ConversionFormat.tiff)
                    }
                    .pickerStyle(.menu)
                    .tint(.psTextPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Color.psFieldInputBg)
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                    )

                    if model.config.conversionFormat != .none {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Frames are converted once before alignment with your RAW exposure and noise settings. \(model.config.conversionFormat == .jpg ? "JPEG reduces precision and uses lossy compression." : "TIFF retains full precision and needs more disk space.")")
                                .font(.psHardwareNote)
                                .foregroundColor(.psTextMuted)

                            Text("Converted frame location")
                                .font(.psFieldLabel)
                                .foregroundColor(.psTextSecondary)

                            HStack(spacing: 8) {
                                TextField("Temporary folder in source folder", text: Binding(
                                    get: { model.config.conversionOutputDirectory?.path ?? "" },
                                    set: { model.config.conversionOutputDirectory = $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
                                ))
                                .font(.psFieldInput)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 10)
                                .background(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(Color.psFieldInputBg)
                                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                                )

                                Button {
                                    showingConversionPicker = true
                                } label: {
                                    Image(systemName: "folder")
                                        .frame(width: 42, height: 42)
                                        .background(
                                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                                .fill(Color.white.opacity(0.08))
                                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.15), lineWidth: 1))
                                        )
                                }
                                .accessibilityLabel("Choose converted frame folder")
                            }

                            Text(model.config.conversionOutputDirectory == nil
                                ? "Leave blank to use a temporary folder inside the source folder, removed on completion, cancellation, or error."
                                : "Converted files are kept in this location."
                            )
                            .font(.psHardwareNote)
                            .foregroundColor(.psTextMuted)
                        }
                        .padding(10)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color.black.opacity(0.2)))
                    }
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Image export format")
                    .font(.psFieldLabel)
                    .foregroundColor(.psTextSecondary)

                Picker("Image export format", selection: $model.config.imageFormat) {
                    Text("TIFF · lossless, source bit depth").tag(ImageFormat.tiff)
                    Text("PNG · lossless, source bit depth").tag(ImageFormat.png)
                    Text("JPEG · smaller, lossy 8-bit").tag(ImageFormat.jpg)
                }
                .pickerStyle(.menu)
                .tint(.psTextPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.psFieldInputBg)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                )

                Text("TIFF and PNG retain 16-bit sources. JPEG is 8-bit at 95% quality. RAW files are developed, not exported as RAW.")
                    .font(.psHardwareNote)
                    .foregroundColor(.psTextMuted)
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(model.exportMode == .images ? "Output folder name or full path" : "Output filename or full path")
                    .font(.psFieldLabel)
                    .foregroundColor(.psTextSecondary)

                TextField(model.exportMode == .images ? "aligned_images" : "aligned_star_trails.tiff", text: $model.config.outputBaseName)
                    .font(.psFieldInput)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Color.psFieldInputBg)
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                    )
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Image export resolution")
                    .font(.psFieldLabel)
                    .foregroundColor(.psTextSecondary)

                Picker("Image export resolution", selection: $model.config.imageResolution) {
                    Text("Source resolution · maximum detail").tag(Resolution.source)
                    Text("4K · up to 3840px").tag(Resolution.k4)
                    Text("2K · up to 2560px").tag(Resolution.k2)
                    Text("1080p · up to 1920px").tag(Resolution.p1080)
                    Text("720p · up to 1280px").tag(Resolution.p720)
                }
                .pickerStyle(.menu)
                .tint(.psTextPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.psFieldInputBg)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                )

                Text("Lower resolutions reduce processing time and file size. Relative destinations are saved inside the loaded source folder. Image sequences require a new folder name.")
                    .font(.psHardwareNote)
                    .foregroundColor(.psTextMuted)
            }

            if model.exportMode == .trails {
                PSToggle(
                    "Also export aligned images",
                    isOn: $model.config.saveFrames,
                    description: "Save the real exposures in a separate folder beside the trail image."
                )

                PSToggle(
                    "Also create a trail-lapse video",
                    isOn: $model.config.videoEnabled
                )

                if model.config.videoEnabled {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Video file format")
                            .font(.psFieldLabel)
                            .foregroundColor(.psTextSecondary)

                        Picker("Video file format", selection: $model.config.videoFormat) {
                            Text("MP4 · broad playback support").tag(VideoFormat.mp4)
                            Text("MOV · editing workflow").tag(VideoFormat.mov)
                        }
                        .pickerStyle(.segmented)

                        Text("Video quality")
                            .font(.psFieldLabel)
                            .foregroundColor(.psTextSecondary)

                        Picker("Video quality", selection: $model.config.quality) {
                            Text("High quality · H.264").tag(VideoQuality.high)
                            Text("ProRes 422 HQ").tag(VideoQuality.prores)
                            Text("Lossless H.264").tag(VideoQuality.lossless)
                            Text("Medium quality").tag(VideoQuality.medium)
                        }
                        .pickerStyle(.menu)
                        .tint(.psTextPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color.psFieldInputBg)
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                        )

                        Text("Video resolution")
                            .font(.psFieldLabel)
                            .foregroundColor(.psTextSecondary)

                        Picker("Video resolution", selection: $model.config.videoResolution) {
                            Text("Source resolution").tag(Resolution.source)
                            Text("4K · up to 3840px").tag(Resolution.k4)
                            Text("2K · up to 2560px").tag(Resolution.k2)
                            Text("1080p · up to 1920px").tag(Resolution.p1080)
                            Text("720p · up to 1280px").tag(Resolution.p720)
                        }
                        .pickerStyle(.menu)
                        .tint(.psTextPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(Color.psFieldInputBg)
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                        )

                        Text("Video is never upscaled. Lower settings reduce video encoding and readback time.")
                            .font(.psHardwareNote)
                            .foregroundColor(.psTextMuted)

                        Picker("Video mode", selection: Binding(
                            get: { model.videoPlaybackMode },
                            set: { model.videoPlaybackMode = $0 }
                        )) {
                            Text("Slow motion").tag(VideoPlaybackMode.slowmo)
                            Text("Hyperlapse").tag(VideoPlaybackMode.hyperlapse)
                        }
                        .pickerStyle(.segmented)

                        if model.videoPlaybackMode == .slowmo {
                            Text("Slow-motion pace")
                                .font(.psFieldLabel)
                                .foregroundColor(.psTextSecondary)

                            Picker("Slow-motion pace", selection: $model.config.videoSlowdown) {
                                Text("1× · Fast").tag(1)
                                Text("2× · Moderate").tag(2)
                                Text("4× · Slow").tag(4)
                                Text("8× · Very slow").tag(8)
                            }
                            .pickerStyle(.menu)
                            .tint(.psTextPrimary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .fill(Color.psFieldInputBg)
                                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.12), lineWidth: 1))
                            )

                            Text("Controls how many video snapshots are written per exposure interval. The final stack still uses every synthetic frame.")
                                .font(.psHardwareNote)
                                .foregroundColor(.psTextMuted)
                        }
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.black.opacity(0.2)))
                }

                AdvancedDisclosure("Recovery options") {
                    VStack(alignment: .leading, spacing: 10) {
                        PSToggle(
                            "Save recovery checkpoints",
                            isOn: $model.config.useCheckpoint
                        )

                        PSToggle(
                            "Resume from checkpoint",
                            isOn: $model.config.resume
                        )
                    }
                }
            }
        }
    }

    // MARK: - Setup Footer
    private var setupFooter: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(footerStatusMessage)
                .font(.system(size: 11, weight: .regular))
                .foregroundColor(.psTextMuted)
                .lineLimit(2)

            if let validationErr = model.validationError {
                Text(validationErr)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(.psWarning)
            }

            PSButton(
                startOrCancelButtonTitle,
                systemImage: model.isCancelling ? nil : (model.isProcessing ? "square.fill" : "arrow.up.right"),
                variant: model.isProcessing ? .cancel : .primary,
                isLoading: model.isCancelling
            ) {
                if model.isProcessing {
                    model.cancelJob()
                } else {
                    model.startJob()
                }
            }
            .disabled(model.isCancelling || (!model.isProcessing && (!model.isReady || model.validationError != nil)))
            .keyboardShortcut("r", modifiers: .command)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(
            LinearGradient(
                colors: [Color.psSurfaceFooterStart, Color.psSurfaceFooter],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }

    private var footerStatusMessage: String {
        if model.isCancelling {
            return "Stopping at the next processing boundary."
        } else if model.isProcessing {
            return "You can cancel while frames and trails are being processed."
        } else if model.isDetecting {
            return "Wait for detection, or cancel it in the image workspace."
        } else if model.config.outputBaseName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && model.sequence.count >= model.minimumFrames {
            return "Enter an output name or full path to continue."
        } else if model.isReady {
            return "Ready when you are. References can be detected automatically."
        } else if !model.sequence.isEmpty && model.sequence.count < model.minimumFrames {
            return "Choose at least \(model.minimumFrames) frames for this alignment mode."
        } else {
            return "Load a sequence to begin."
        }
    }

    private var startOrCancelButtonTitle: String {
        if model.isCancelling {
            return "Cancelling…"
        } else if model.isProcessing {
            switch model.jobState.stage {
            case .conversion:
                return "Cancel conversion"
            case .pass2:
                return model.exportMode == .images ? "Cancel image export" : "Cancel trail creation"
            case .videoRender:
                return "Cancel video render"
            default:
                return "Cancel alignment"
            }
        } else {
            return model.exportMode == .images ? "Align & export images" : "Create star trails"
        }
    }
}
