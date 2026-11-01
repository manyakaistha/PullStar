import type { ReactNode } from "react";
import { Button } from "./ui/Button";
import { Toggle } from "./ui/Toggle";
import { Slider } from "./ui/Slider";
import {
  FolderOpen,
  ArrowUpRight,
  Loader2,
  ChevronDown,
  SlidersHorizontal,
  Square,
} from "lucide-react";

export interface ParameterBaysProps {
  rawNoiseReduction: boolean;
  setRawNoiseReduction: (value: boolean) => void;
  rawExposureEv: number;
  setRawExposureEv: (value: number) => void;
  inputDir: string;
  setInputDir: (dir: string) => void;
  onBrowse: () => void;
  files: string[];
  onScan: () => void;
  sortByTime: boolean;
  setSortByTime: (val: boolean) => void;
  gapCount: number;

  kalman: boolean;
  setKalman: (val: boolean) => void;
  useRotation: boolean;
  setUseRotation: (val: boolean) => void;

  extension: number;
  setExtension: (val: number) => void;
  tailTaper: number;
  setTailTaper: (val: number) => void;
  tailAngleThreshold: number;
  setTailAngleThreshold: (val: number) => void;
  ghosts: number;
  setGhosts: (val: number) => void;
  syntheticFade: number;
  setSyntheticFade: (val: number) => void;
  fgMask: boolean;
  setFgMask: (val: boolean) => void;

  chronoGap: boolean;
  setChronoGap: (val: boolean) => void;

  videoExport: boolean;
  setVideoExport: (val: boolean) => void;
  videoQuality: string;
  setVideoQuality: (val: string) => void;
  videoMode: "slowmo" | "hyperlapse";
  setVideoMode: (val: "slowmo" | "hyperlapse") => void;
  videoSlowdown: number;
  setVideoSlowdown: (val: number) => void;
  imageResolution: string;
  setImageResolution: (val: string) => void;
  videoResolution: string;
  setVideoResolution: (val: string) => void;

  exportMode: string;
  setExportMode: (value: string) => void;
  imageFormat: string;
  setImageFormat: (value: string) => void;
  videoFormat: string;
  setVideoFormat: (value: string) => void;
  saveFrames: boolean;
  setSaveFrames: (value: boolean) => void;
  outputName: string;
  setOutputName: (val: string) => void;
  conversionFormat: "none" | "jpg" | "tiff";
  setConversionFormat: (val: "none" | "jpg" | "tiff") => void;
  conversionOutputDir: string;
  setConversionOutputDir: (val: string) => void;
  onBrowseConversionDir: () => void;
  useCheckpoint: boolean;
  setUseCheckpoint: (val: boolean) => void;
  resume: boolean;
  setResume: (val: boolean) => void;

  onStartJob: () => void;
  onCancelJob: () => void;
  isCancelling: boolean;
  processingStage?: string;
  isDetecting: boolean;
  isProcessing: boolean;
  isScanning: boolean;
  scanError: string;
  loadedDir: string;
  computeBackend: string;
  setComputeBackend: (value: string) => void;
  hardwareSummary: string;
}

function SetupSection({
  number,
  title,
  description,
  children,
}: {
  number: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="setup-section">
      <div className="setup-section-heading">
        <span className="step-number">{number}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>
      <div className="setup-section-body">{children}</div>
    </section>
  );
}
function Advanced({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="setup-details">
      <summary>
        {title}
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <div className="advanced-body">{children}</div>
    </details>
  );
}

export function ParameterBays(p: ParameterBaysProps) {
  const minimumFrames = p.exportMode === "images" ? 3 : 10;
  const ready =
    !!p.loadedDir &&
    p.files.length >= minimumFrames &&
    !!p.outputName.trim() &&
    !p.isScanning && !p.isDetecting;
  return (
    <div className="setup-content">
      <div className="setup-title">
        <div>
          <p className="eyebrow">A GOOD STACK STARTS HERE</p>
          <h2>Alignment setup</h2>
        </div>
        <SlidersHorizontal size={18} strokeWidth={1.5} aria-hidden="true" />
      </div>
      <div className="setup-scroll">
        <fieldset className="setup-fields" disabled={p.isProcessing || p.isDetecting}>
          <SetupSection
            number="01"
            title="Source frames"
            description="Choose the sequence you want to align."
          >
            <label className="field-label" htmlFor="source-folder">
              Image folder
            </label>
            <div className="source-input-row">
              <input
                id="source-folder"
                className="field-input"
                value={p.inputDir}
                onChange={(e) => p.setInputDir(e.target.value)}
                placeholder="/path/to/your/night-sky-images"
                onKeyDown={(e) => {
                  if (e.key === "Enter") p.onScan();
                }}
              />
              <Button onClick={p.onBrowse} aria-label="Choose image folder">
                <FolderOpen size={16} />
              </Button>
            </div>
            <Button
              className="load-frames-button"
              onClick={p.onScan}
              disabled={p.isScanning || !p.inputDir.trim()}
            >
              {p.isScanning ? (
                <Loader2 size={14} className="motion-safe:animate-spin" />
              ) : (
                <ArrowUpRight size={14} />
              )}
              {p.isScanning ? "Loading sequence…" : "Load frames"}
            </Button>
            {p.scanError && (
              <p className="inline-error" role="alert">
                {p.scanError}
              </p>
            )}
            {p.files.length > 0 && (
              <div className="source-summary">
                <span className="status-dot" />
                {p.files.length} frames loaded
                <span>{p.gapCount > 0 ? `${p.gapCount} gaps` : "Ready"}</span>
              </div>
            )}
            <Advanced title="Sequence order">
              <div className="setting-row">
                <span>Sort frames by</span>
                <div
                  className="segmented-control"
                  role="group"
                  aria-label="Sequence sort mode"
                >
                  <button
                    type="button"
                    className="segment"
                    aria-pressed={p.sortByTime}
                    onClick={() => p.setSortByTime(true)}
                  >
                    Time
                  </button>
                  <button
                    type="button"
                    className="segment"
                    aria-pressed={!p.sortByTime}
                    onClick={() => p.setSortByTime(false)}
                  >
                    Name
                  </button>
                </div>
              </div>
            </Advanced>
            <Advanced title="Processing hardware">
              <label className="field-label" htmlFor="processing-device">Processing device</label>
              <select id="processing-device" className="field-input" value={p.computeBackend}
                onChange={(event) => p.setComputeBackend(event.target.value)}>
                <option value="auto">Automatic · CPU + supported GPU</option>
                <option value="cpu">CPU only</option>
              </select>
              <p className="hardware-note">{p.hardwareSummary}</p>
              <p className="hardware-note">Parallel work is limited by available cores and memory.</p>
            </Advanced>
            {p.files.some((file) => /\.(dng|nef|cr2|cr3|arw)$/i.test(file)) && (
              <Advanced title="High-noise RAW recovery">
                <Toggle label="Recover faint and streaked stars" checked={p.rawNoiseReduction}
                  onChange={p.setRawNoiseReduction}
                  description="Use sensor data for detection and reduce noise before stacking." />
                <label className="field-label" htmlFor="raw-exposure">RAW exposure boost</label>
                <select id="raw-exposure" className="field-input" value={p.rawExposureEv}
                  onChange={(event) => p.setRawExposureEv(Number(event.target.value))}>
                  <option value={0}>Original exposure</option>
                  <option value={1}>+1 stop</option>
                  <option value={2}>+2 stops</option>
                  <option value={3}>+3 stops</option>
                </select>
                <p className="hardware-note">Applies to the RAW stack. Source files stay unchanged.</p>
              </Advanced>
            )}
          </SetupSection>
          <SetupSection
            number="02"
            title="Build your alignment"
            description="Automatic by default. Manual references are optional."
          >
            <Advanced title="Manual reference tracking settings">
            <p className="hardware-note">These settings apply when you pick Polaris manually. Automatic field matching estimates camera motion directly.</p>
            <Toggle
              label="Smooth star tracking"
              checked={p.kalman}
              onChange={p.setKalman}
              description="Kalman filtering reduces frame-to-frame drift."
            />
            <Toggle
              label="Correct field rotation"
              checked={p.useRotation}
              onChange={p.setUseRotation}
              description="Pick a second reference star when enabled."
            />
            </Advanced>
            <label className="field-label" htmlFor="export-mode">What would you like to create?</label>
            <select id="export-mode" className="field-input" value={p.exportMode}
              onChange={(event) => p.setExportMode(event.target.value)}>
              <option value="trails">Star trails · image and optional video</option>
              <option value="images">Aligned images only · edit in another app</option>
            </select>
            <p className="hardware-note">{p.exportMode === "images"
              ? "Correct camera wobble and export real exposures with a shared crop. Sky motion is preserved. No stacking, synthetic frames, or video rendering."
              : "Align your exposures, then blend them into a star-trail image."}</p>
            {p.exportMode === "trails" && <>
            <div className="setting-divider" />
            <Slider
              label="Trail extension"
              value={p.extension}
              min={1}
              max={5}
              step={0.1}
              unit="×"
              onChangeVal={p.setExtension}
              helperText="1× preserves the original trail length."
            />
            <Toggle
              label="Preserve the foreground"
              checked={p.fgMask}
              onChange={p.setFgMask}
            />
            <Toggle
              label="Fill timeline gaps"
              checked={p.chronoGap}
              onChange={p.setChronoGap}
              description={
                p.gapCount
                  ? `${p.gapCount} missing intervals detected.`
                  : "Interpolate missing exposure intervals."
              }
            />
            <Advanced title="Fine-tune trail synthesis">
              <Slider
                label="Tail taper"
                value={p.tailTaper}
                min={0}
                max={1}
                step={0.05}
                onChangeVal={p.setTailTaper}
                helperText="Fades synthetic trail brightness toward its far end."
              />
              <Slider
                label="Tail angle cutoff"
                value={p.tailAngleThreshold}
                min={0}
                max={360}
                step={1}
                unit="°"
                onChangeVal={p.setTailAngleThreshold}
                helperText="0° keeps the full extension; otherwise it stops after this angle."
              />
              <Slider
                label="Synthetic frames per exposure"
                value={p.ghosts}
                min={1}
                max={20}
                onChangeVal={p.setGhosts}
              />
              <Slider
                label="Synthetic fade"
                value={p.syntheticFade}
                min={0}
                max={1}
                step={0.05}
                onChangeVal={p.setSyntheticFade}
              />
            </Advanced>
            </>}
          </SetupSection>
          <SetupSection
            number="03"
            title="Output"
            description="Choose formats and a destination for your exports."
          >
            <Advanced title="Develop inputs before alignment">
            <label className="field-label" htmlFor="conversion-format-select">
              Stacking input format
            </label>
            <select
              id="conversion-format-select"
              className="field-input"
              value={p.conversionFormat}
              onChange={(e) => p.setConversionFormat(e.target.value as "none" | "jpg" | "tiff")}
            >
              <option value="none">Use original files</option>
              <option value="jpg">JPEG · smaller, 8-bit</option>
              <option value="tiff">TIFF · lossless, 16-bit</option>
            </select>
            {p.conversionFormat !== "none" && (
              <div className="conversion-options">
                <p className="hardware-note">
                  Frames are converted once before alignment with your RAW exposure and noise settings.
                  {p.conversionFormat === "jpg" ? " JPEG reduces precision and uses lossy compression." : " TIFF retains full precision and needs more disk space."}
                </p>
                <label className="field-label" htmlFor="conversion-output-dir">
                  Converted frame location
                </label>
                <div className="source-input-row">
                  <input
                    id="conversion-output-dir"
                    className="field-input"
                    value={p.conversionOutputDir}
                    onChange={(e) => p.setConversionOutputDir(e.target.value)}
                    placeholder="Temporary folder in source folder"
                  />
                  <Button onClick={p.onBrowseConversionDir} aria-label="Choose converted frame folder">
                    <FolderOpen size={16} />
                  </Button>
                </div>
                <p className="hardware-note">
                  {p.conversionOutputDir.trim()
                    ? "Converted files are kept in this location."
                    : "Leave blank to use a temporary folder inside the source folder, removed on completion, cancellation, or error."}
                </p>
              </div>
            )}
            </Advanced>
            <label className="field-label" htmlFor="image-export-format">Image export format</label>
            <select id="image-export-format" className="field-input" value={p.imageFormat}
              onChange={(event) => p.setImageFormat(event.target.value)}>
              <option value="tiff">TIFF · lossless, source bit depth</option>
              <option value="png">PNG · lossless, source bit depth</option>
              <option value="jpg">JPEG · smaller, lossy 8-bit</option>
            </select>
            <p className="hardware-note">TIFF and PNG retain 16-bit sources. JPEG is 8-bit at 95% quality. RAW files are developed, not exported as RAW.</p>
            <label className="field-label" htmlFor="output-filename-input">
              {p.exportMode === "images" ? "Output folder name or full path" : "Output filename or full path"}
            </label>
            <input
              id="output-filename-input"
              className="field-input"
              value={p.outputName}
              onChange={(e) => p.setOutputName(e.target.value)}
              placeholder={p.exportMode === "images" ? "aligned_images" : "aligned_star_trails.tiff"}
            />
            <label className="field-label" htmlFor="image-resolution-select">
              Image export resolution
            </label>
            <select
              id="image-resolution-select"
              className="field-input"
              value={p.imageResolution}
              onChange={(e) => p.setImageResolution(e.target.value)}
            >
              <option value="source">Source resolution · maximum detail</option>
              <option value="4k">4K · up to 3840px</option>
              <option value="2k">2K · up to 2560px</option>
              <option value="1080p">1080p · up to 1920px</option>
              <option value="720p">720p · up to 1280px</option>
            </select>
            <p className="hardware-note">
              Lower resolutions reduce processing time and file size. Relative destinations are saved inside the loaded source folder. Image sequences require a new folder name.
            </p>
            {p.exportMode === "trails" && <>
            <Toggle label="Also export aligned images" checked={p.saveFrames} onChange={p.setSaveFrames}
              description="Save the real exposures in a separate folder beside the trail image." />
            <Toggle
              label="Also create a trail-lapse video"
              checked={p.videoExport}
              onChange={p.setVideoExport}
            />
            {p.videoExport && (
              <div className="video-options">
                <label className="field-label" htmlFor="video-format">Video file format</label>
                <select id="video-format" className="field-input" value={p.videoFormat}
                  onChange={(event) => p.setVideoFormat(event.target.value)}>
                  <option value="mp4">MP4 · broad playback support</option>
                  <option value="mov">MOV · editing workflow</option>
                </select>
                <label className="field-label" htmlFor="video-codec-select">
                  Video quality
                </label>
                <select
                  id="video-codec-select"
                  className="field-input"
                  value={p.videoQuality}
                  onChange={(e) => p.setVideoQuality(e.target.value)}
                >
                  <option value="high">High quality · H.264</option>
                  <option value="prores">ProRes 422 HQ</option>
                  <option value="lossless">Lossless H.264</option>
                  <option value="medium">Medium quality</option>

                </select>
                <label className="field-label" htmlFor="video-resolution-select">
                  Video resolution
                </label>
                <select
                  id="video-resolution-select"
                  className="field-input"
                  value={p.videoResolution}
                  onChange={(e) => p.setVideoResolution(e.target.value)}
                >
                  <option value="source">Source resolution</option>
                  <option value="4k">4K · up to 3840px</option>
                  <option value="2k">2K · up to 2560px</option>
                  <option value="1080p">1080p · up to 1920px</option>
                  <option value="720p">720p · up to 1280px</option>
                </select>
                <p className="hardware-note">
                  Video is never upscaled. Lower settings reduce video encoding and readback time.
                </p>
                <div
                  className="segmented-control"
                  role="group"
                  aria-label="Video mode"
                >
                  <button
                    type="button"
                    className="segment"
                    aria-pressed={p.videoMode === "slowmo"}
                    onClick={() => p.setVideoMode("slowmo")}
                  >
                    Slow motion
                  </button>
                  <button
                    type="button"
                    className="segment"
                    aria-pressed={p.videoMode === "hyperlapse"}
                    onClick={() => p.setVideoMode("hyperlapse")}
                  >
                    Hyperlapse
                  </button>
                </div>
                {p.videoMode === "slowmo" && (
                  <>
                    <label className="field-label" htmlFor="video-slowdown-select">
                      Slow-motion pace
                    </label>
                    <select
                      id="video-slowdown-select"
                      className="field-input"
                      value={p.videoSlowdown}
                      onChange={(e) => p.setVideoSlowdown(Number(e.target.value))}
                    >
                      <option value={1}>1× · Fast</option>
                      <option value={2}>2× · Moderate</option>
                      <option value={4}>4× · Slow</option>
                      <option value={8}>8× · Very slow</option>
                    </select>
                    <p className="hardware-note">
                      Controls how many video snapshots are written per exposure interval.
                      The final stack still uses every synthetic frame.
                    </p>
                  </>
                )}
              </div>
            )}
            </>}
            {p.exportMode === "trails" && <Advanced title="Recovery options">
              <Toggle
                label="Save recovery checkpoints"
                checked={p.useCheckpoint}
                onChange={p.setUseCheckpoint}
              />
              <Toggle
                label="Resume from checkpoint"
                checked={p.resume}
                onChange={p.setResume}
              />
            </Advanced>}
          </SetupSection>
        </fieldset>
      </div>
      <div className="setup-footer">
        <p>
          {p.isCancelling
            ? "Stopping at the next processing boundary."
            : p.isProcessing
            ? "You can cancel while frames and trails are being processed."
            : p.isDetecting
              ? "Wait for detection, or cancel it in the image workspace."
            : !p.outputName.trim() && p.files.length >= minimumFrames
              ? "Enter an output name or full path to continue."
            : ready
              ? "Ready when you are. References can be detected automatically."
              : p.files.length > 0 && p.files.length < minimumFrames
                ? `Choose at least ${minimumFrames} frames for this alignment mode.`
                : "Load a sequence to begin."}
        </p>
        <button
          type="button"
          onClick={p.isProcessing ? p.onCancelJob : p.onStartJob}
          disabled={p.isCancelling || (!p.isProcessing && !ready)}
          className={`tactile-button start-alignment ${p.isProcessing ? "action-cancel" : ""}`}
        >
          {p.isCancelling ? (
            <Loader2 size={16} className="motion-safe:animate-spin" />
          ) : p.isProcessing ? (
            <Square size={14} />
          ) : (
            <ArrowUpRight size={16} />
          )}
          <span>
            {p.isCancelling ? "Cancelling…"
              : p.isProcessing
                ? p.processingStage === "conversion" ? "Cancel conversion"
                  : p.processingStage === "pass2" ? p.exportMode === "images" ? "Cancel image export" : "Cancel trail creation"
                  : p.processingStage === "video_render" ? "Cancel video render" : "Cancel alignment"
                : p.exportMode === "images" ? "Align & export images" : "Create star trails"}
          </span>
        </button>
      </div>
    </div>
  );
}
