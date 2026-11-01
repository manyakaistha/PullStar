import { API_ORIGIN } from "./api";
import { JobAction, isActiveJob } from "./jobAction";
import { useState, useEffect, useRef } from "react";
import { ParameterBays } from "./components/ParameterBays";
import { CelestialViewfinder } from "./components/CelestialViewfinder";
import { LiveTelemetry, type JobState } from "./components/LiveTelemetry";
import { WorkspaceNav, type WorkspaceView } from "./components/WorkspaceNav";
import { ArrowRight, Check, Crosshair, FolderOpen } from "lucide-react";

function App() {
  const [activeView, setActiveView] = useState<WorkspaceView>("workspace");
  const [isTelemetryCollapsed, setIsTelemetryCollapsed] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [loadedDir, setLoadedDir] = useState("");
  const scanRequestRef = useRef(0);

  const [inputDir, setInputDir] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const [gapCount, setGapCount] = useState(0);
  const [sortByTime, setSortByTime] = useState(true);

  const [polaris, setPolaris] = useState<{ x: number; y: number } | null>(null);
  const [refStar2, setRefStar2] = useState<{ x: number; y: number } | null>(
    null,
  );

  // Parameters
  const [kalman, setKalman] = useState(true);
  const [useRotation, setUseRotation] = useState(false);

  const [extension, setExtension] = useState(1.0);
  const [tailTaper, setTailTaper] = useState(0.0);
  const [tailAngleThreshold, setTailAngleThreshold] = useState(0.0);
  const [ghosts, setGhosts] = useState(10);
  const [syntheticFade, setSyntheticFade] = useState(0.2);
  const [fgMask, setFgMask] = useState(true);
  const [chronoGap, setChronoGap] = useState(false);

  const [videoExport, setVideoExport] = useState(false);
  const [videoQuality, setVideoQuality] = useState("high");
  const [videoMode, setVideoMode] = useState<"slowmo" | "hyperlapse">("slowmo");
  const [videoSlowdown, setVideoSlowdown] = useState(1);
  const [imageResolution, setImageResolution] = useState("source");
  const [videoResolution, setVideoResolution] = useState("1080p");

  const [exportMode, setExportMode] = useState("trails");
  const [imageFormat, setImageFormat] = useState("tiff");
  const [videoFormat, setVideoFormat] = useState("mp4");
  const [saveFrames, setSaveFrames] = useState(false);
  const [outputName, setOutputName] = useState("aligned_star_trails.tiff");
  const [conversionFormat, setConversionFormat] = useState<"none" | "jpg" | "tiff">("none");
  const [conversionOutputDir, setConversionOutputDir] = useState("");
  const [useCheckpoint, setUseCheckpoint] = useState(true);
  const [resume, setResume] = useState(false);
  const [computeBackend, setComputeBackend] = useState("auto");
  const [rawNoiseReduction, setRawNoiseReduction] = useState(true);
  const [rawExposureEv, setRawExposureEv] = useState(0);
  const [hardwareSummary, setHardwareSummary] = useState("Hardware is detected automatically.");

  // Job & Telemetry state
  const [jobState, setJobState] = useState<JobState>({ status: "idle" });
  const [isDetecting, setIsDetecting] = useState(false);
  const jobActionRef = useRef<JobAction | null>(null);
  const isProcessing = isActiveJob(jobState);

  const hasResult = jobState.status === "completed" && !!jobState.result_path;

  // Keep the loaded sequence separate from an edited directory field.
  const scanDirectory = async (dirToScan = inputDir) => {
    if (!dirToScan.trim() || isProcessing || isDetecting) return;
    const request = ++scanRequestRef.current;
    jobActionRef.current?.dispose();
    jobActionRef.current = null;
    setIsScanning(true);
    setScanError("");
    setFiles([]);
    setGapCount(0);
    setLoadedDir("");
    setPolaris(null);
    setRefStar2(null);
    setActiveView("workspace");
    setJobState({ status: "idle" });
    try {
      const response = await fetch(`${API_ORIGIN}/api/images/list`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dirToScan, sort_by_time: sortByTime }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "Could not load this folder.");
      if (request !== scanRequestRef.current) return;
      if (!data.files?.length)
        throw new Error(
          "No supported images found. Choose a folder with JPEG, PNG, TIFF, or RAW files.",
        );
      setFiles(data.files);
      setLoadedDir(dirToScan);
      const metadata = await fetch(`${API_ORIGIN}/api/images/metadata`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dirToScan, sort_by_time: sortByTime }),
      });
      if (metadata.ok) {
        const result = await metadata.json();
        if (request === scanRequestRef.current) {
          setGapCount(
            (result.metadata || []).filter(
              (m: { gap_detected?: boolean }) => m.gap_detected,
            ).length,
          );
        }
      }
    } catch (error) {
      if (request === scanRequestRef.current)
        setScanError(
          error instanceof TypeError
            ? "Unable to connect to the local image service. Make sure the backend is running."
            : error instanceof Error
              ? error.message
              : "Unable to load this folder.",
        );
    } finally {
      if (request === scanRequestRef.current) setIsScanning(false);
    }
  };

  const handleBrowse = async () => {
    if (isProcessing) return;
    if (window.starAligner) {
      try {
        const chosen = await window.starAligner.pickDirectory();
        if (chosen) {
          setInputDir(chosen);
          void scanDirectory(chosen);
        }
      } catch {
        setScanError(
          "The folder picker could not open. Enter a path below instead.",
        );
      }
    } else {
      document.getElementById("source-folder")?.focus();
      document
        .getElementById("setup-pane")
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  };

  const handleBrowseConversionDir = async () => {
    if (isProcessing) return;
    if (window.starAligner) {
      try {
        const chosen = await window.starAligner.pickDirectory("converted");
        if (chosen) setConversionOutputDir(chosen);
      } catch {
        setScanError("The converted-frame folder picker could not open. Enter a path below instead.");
      }
    } else {
      document.getElementById("conversion-output-dir")?.focus();
    }
  };

  const startJob = async () => {
    if (
      isProcessing ||
      isDetecting ||
      jobActionRef.current?.active ||
      isScanning ||
      !loadedDir ||
      files.length < (exportMode === "images" ? 3 : 10) ||
      !outputName.trim()
    )
      return;
    setIsTelemetryCollapsed(false);
    setActiveView("workspace");
    setJobState({
      status: "running",
      stage: "preparation",
      progress: 0,
      video_enabled: exportMode === "trails" && videoExport,
      no_stack: exportMode === "images",
      conversion_format: conversionFormat,
      first_frame_path: files[0],
      live_preview_path: null,
    });

    try {
      const destination = outputName.trim();
      const isAbsolute = destination.startsWith("/") || /^[a-zA-Z]:[\\/]/.test(destination) || destination.startsWith("\\\\");
      const outputPath = isAbsolute ? destination : `${loadedDir}/${destination}`;
      const payload = {
        raw_noise_reduction: rawNoiseReduction,
        raw_exposure_ev: rawExposureEv,
        input_dir: loadedDir,
        output_file: outputPath,
        extension_factor: exportMode === "images" ? 1 : extension,
        save_frames: exportMode === "images" || saveFrames,
        image_format: imageFormat,
        video_format: videoFormat,
        tail_taper_strength: tailTaper,
        tail_angle_threshold: tailAngleThreshold,
        use_rotation: useRotation,
        use_kalman: kalman,
        ghost_frames_per_real: ghosts,
        synthetic_fade_factor: syntheticFade,
        use_foreground_mask: fgMask,
        fill_gaps: exportMode === "trails" && chronoGap,
        video_enabled: exportMode === "trails" && videoExport,
        no_stack: exportMode === "images",
        video_fps: 30,
        video_slowdown: videoSlowdown,
        image_resolution: imageResolution,
        video_resolution: videoResolution,
        quality: videoQuality,
        video_hyperlapse: videoMode === "hyperlapse",
        use_checkpoint: exportMode === "trails" && useCheckpoint,
        resume: exportMode === "trails" && resume,
        sort_by_time: sortByTime,
        polaris_x: polaris ? polaris.x : null,
        polaris_y: polaris ? polaris.y : null,
        star2_x: refStar2 ? refStar2.x : null,
        star2_y: refStar2 ? refStar2.y : null,
        compute_backend: computeBackend,
        conversion_format: conversionFormat,
        conversion_output_dir: conversionFormat !== "none" ? conversionOutputDir.trim() || null : null,
      };

      const action = new JobAction(API_ORIGIN, (data) => {
        if (jobActionRef.current !== action) return;
        setJobState((previous) => ({ ...previous, ...data,
          video_enabled: exportMode === "trails" && videoExport,
          no_stack: exportMode === "images", first_frame_path: files[0] }));
        if (data.status === "completed") setActiveView("results");
      });
      jobActionRef.current = action;
      await action.start("/api/jobs", payload);
    } catch (err) {
      console.error(err);
      setJobState({
        status: "failed",
        error: err instanceof Error ? err.message : "Unable to start alignment",
      });
    }
  };

  const cancelJob = () => {
    jobActionRef.current?.cancel();
  };

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_ORIGIN}/api/system/compute`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (!data || controller.signal.aborted) return;
        const graphics = data.gpus?.map((gpu: { name: string }) => gpu.name).join(", ");
        setHardwareSummary(`${data.cpu_count} CPU cores${graphics ? ` · ${graphics}` : " · CPU rendering available"}`);
      }).catch(() => {});
    return () => controller.abort();
  }, []);

  // Demo URL parameter initializations
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const viewParam = params.get("view");
    const dirParam = params.get("dir");

    if (dirParam) {
      setInputDir(dirParam);
      void scanDirectory(dirParam);
    }

    if (viewParam === "autodetect") {
      setPolaris({ x: 1540.2, y: 1080.5 });
      setRefStar2({ x: 1120.0, y: 1650.0 });
      setUseRotation(true);
    } else if (viewParam === "telemetry") {
      setPolaris({ x: 1540.2, y: 1080.5 });
      setJobState({
        status: "running",
        stage: "pass2",
        progress: 0.68,
        overall_progress: 0.8012,
        current: 48,
        total: 70,
        fps: 24.2,
        drift_x: 0.42,
        drift_y: -0.18,
        first_frame_path: "corr_to_jpeg/IMG_20260129_222517658.jpg",
      });
    } else if (viewParam === "split" || viewParam === "complete") {
      setJobState({
        status: "completed",
        stage: "done",
        progress: 1.0,
        current: 192,
        total: 192,
        result_path: "corr_to_jpeg/outputs/aligned_star_trails_sample.tiff",
        first_frame_path: "corr_to_jpeg/IMG_20260129_222517658.jpg",
      });
      setActiveView("results");
    }

    return () => {
      jobActionRef.current?.dispose();
    };
  }, []);

  return (
    <div className="workspace-shell studio-shell">
      <WorkspaceNav
        activeView={activeView}
        onSelectView={setActiveView}
        hasResult={hasResult}
        jobState={jobState}
      />
      <div className="studio-intro">
        <h1>Alignment studio</h1>
        <ol className="workflow-steps" aria-label="Alignment workflow">
          <li className={files.length ? "done" : "current"}>
            <span>{files.length ? <Check size={12} /> : "01"}</span>Load frames
          </li>
          <ArrowRight size={12} aria-hidden="true" />
          <li className={polaris || hasResult ? "done" : files.length ? "current" : ""}>
            <span>{polaris || hasResult ? <Check size={12} /> : "02"}</span>References (optional)
          </li>
          <ArrowRight size={12} aria-hidden="true" />
          <li className={hasResult ? "done" : isProcessing ? "current" : ""}>
            <span>{hasResult ? <Check size={12} /> : "03"}</span>Align & export
          </li>
        </ol>
      </div>
      <div className="studio-grid">
        <main className="studio-main">
          <div className="workspace-caption">
            <div>
              <span className="caption-icon">
                <Crosshair size={16} />
              </span>
              <span>
                {activeView === "results" && hasResult
                  ? jobState.no_stack ? "Your aligned images" : "Your aligned stack"
                  : "Image workspace"}
              </span>
            </div>
            <span className="caption-meta">
              {files.length
                ? `${files.length} frames · ${loadedDir.split("/").filter(Boolean).pop()}`
                : "Original pixels. Precise alignment."}
            </span>
          </div>
          {activeView === "results" && hasResult ? (
            <section
              className="results-stage glass-surface"
              aria-label="Alignment results"
            >
              <LiveTelemetry jobState={jobState} showcaseOnly />
            </section>
          ) : (
            <section className="image-stage" aria-label="Image workspace">
              <CelestialViewfinder
                rawNoiseReduction={rawNoiseReduction}
                sortByTime={sortByTime}
                inputDir={loadedDir}
                files={files}
                gapCount={gapCount}
                imageSrc={
                  files.length
                    ? `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(files[0])}`
                    : undefined
                }
                livePreviewSrc={
                  isProcessing && jobState.live_preview_path
                    ? `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(jobState.live_preview_path)}&max_size=2048&v=${jobState.live_preview_revision ?? 0}`
                    : undefined
                }
                polaris={polaris}
                onSetPolaris={setPolaris}
                refStar2={refStar2}
                onSetRefStar2={setRefStar2}
                onBrowseFolder={handleBrowse}
                isProcessing={isProcessing}
                onDetectionActivityChange={setIsDetecting}
              />
            </section>
          )}
          {jobState.status === "failed" && (
            <div className="studio-error" role="alert">
              <strong>Alignment needs attention</strong>
              <p>
                {jobState.error ||
                  "The job could not complete. Review your source and settings, then try again."}
              </p>
            </div>
          )}
          {isProcessing && jobState.error && (
            <p className="inline-error" role="alert">{jobState.error}</p>
          )}
          <section
            className="telemetry-stage glass-surface"
            aria-label="Processing activity"
          >
            <LiveTelemetry
              jobState={jobState}
              isCollapsed={isTelemetryCollapsed}
              onToggleCollapse={() => setIsTelemetryCollapsed((prev) => !prev)}
            />
          </section>
          <p className="workspace-note">
            <FolderOpen size={12} aria-hidden="true" />
            Your images stay on this computer. Alignment runs locally.
          </p>
        </main>
        <aside
          id="setup-pane"
          className="setup-pane glass-surface"
          aria-label="Alignment setup"
        >
          <ParameterBays
            rawNoiseReduction={rawNoiseReduction}
            setRawNoiseReduction={setRawNoiseReduction}
            rawExposureEv={rawExposureEv}
            setRawExposureEv={setRawExposureEv}
            inputDir={inputDir}
            setInputDir={setInputDir}
            onBrowse={handleBrowse}
            files={files}
            onScan={() => scanDirectory()}
            sortByTime={sortByTime}
            setSortByTime={(value) => {
              setSortByTime(value);
              setFiles([]);
              setLoadedDir("");
              setPolaris(null);
              setRefStar2(null);
              setScanError("Sequence order changed. Load frames again to apply it before selecting references.");
            }}
            gapCount={gapCount}
            kalman={kalman}
            setKalman={setKalman}
            useRotation={useRotation}
            setUseRotation={setUseRotation}
            extension={extension}
            setExtension={setExtension}
            tailTaper={tailTaper}
            setTailTaper={setTailTaper}
            tailAngleThreshold={tailAngleThreshold}
            setTailAngleThreshold={setTailAngleThreshold}
            ghosts={ghosts}
            setGhosts={setGhosts}
            syntheticFade={syntheticFade}
            setSyntheticFade={setSyntheticFade}
            fgMask={fgMask}
            setFgMask={setFgMask}
            chronoGap={chronoGap}
            setChronoGap={setChronoGap}
            videoExport={videoExport}
            setVideoExport={setVideoExport}
            videoQuality={videoQuality}
            setVideoQuality={(quality) => { setVideoQuality(quality); if (quality === "prores") setVideoFormat("mov"); }}
            videoMode={videoMode}
            setVideoMode={setVideoMode}
            videoSlowdown={videoSlowdown}
            setVideoSlowdown={setVideoSlowdown}
            imageResolution={imageResolution}
            setImageResolution={setImageResolution}
            videoResolution={videoResolution}
            setVideoResolution={setVideoResolution}
            exportMode={exportMode}
            setExportMode={(mode) => {
              setExportMode(mode);
              setOutputName(mode === "images" ? "aligned_images" : `aligned_star_trails.${imageFormat}`);
            }}
            imageFormat={imageFormat}
            setImageFormat={(format) => {
              setImageFormat(format);
              if (exportMode === "trails") setOutputName((name) => name.replace(/\.[^./\\]+$/, "") + "." + format);
            }}
            videoFormat={videoFormat}
            setVideoFormat={(format) => {
              setVideoFormat(format);
              if (format === "mp4" && videoQuality === "prores") setVideoQuality("high");
            }}
            saveFrames={saveFrames}
            setSaveFrames={setSaveFrames}
            outputName={outputName}
            setOutputName={setOutputName}
            conversionFormat={conversionFormat}
            setConversionFormat={setConversionFormat}
            conversionOutputDir={conversionOutputDir}
            setConversionOutputDir={setConversionOutputDir}
            onBrowseConversionDir={handleBrowseConversionDir}
            useCheckpoint={useCheckpoint}
            setUseCheckpoint={setUseCheckpoint}
            resume={resume}
            setResume={setResume}
            onStartJob={startJob}
            onCancelJob={cancelJob}
            isCancelling={jobState.status === "cancelling"}
            processingStage={jobState.stage}
            isDetecting={isDetecting}
            isProcessing={isProcessing}
            isScanning={isScanning}
            scanError={scanError}
            loadedDir={loadedDir}
            computeBackend={computeBackend}
            setComputeBackend={setComputeBackend}
            hardwareSummary={hardwareSummary}
          />
        </aside>
      </div>
    </div>
  );
}

export default App;
