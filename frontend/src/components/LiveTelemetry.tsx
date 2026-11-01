import { API_ORIGIN } from "../api";
import { isActiveJob, type JobState } from "../jobAction";
export type { JobState } from "../jobAction";
import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type KeyboardEvent,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  Check,
  ChevronDown,
  Loader2,
} from "lucide-react";
interface LiveTelemetryProps {
  jobState?: JobState;
  showcaseOnly?: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}
const allStages = [
  { id: "preparation", label: "Prepare" },
  { id: "conversion", label: "Convert frames" },
  { id: "pass1", label: "Track stars" },
  { id: "crop_calc", label: "Calculate crop" },
  { id: "pass2", label: "Stack frames" },
  { id: "video_render", label: "Render video" },
];
const preview = (path: string) =>
  `${API_ORIGIN}/api/images/preview?path=${encodeURIComponent(path)}`;
export function LiveTelemetry({
  jobState,
  showcaseOnly = false,
  isCollapsed = false,
  onToggleCollapse,
}: LiveTelemetryProps) {
  const stages = allStages.map((stage) => stage.id === "pass2" && jobState?.no_stack ? { ...stage, label: "Export images" } : stage).filter(
    (stage) => (stage.id !== "video_render" || jobState?.video_enabled)
      && (stage.id !== "conversion" || (jobState?.conversion_format && jobState.conversion_format !== "none")),
  );
  const [points, setPoints] = useState<{ x: number; y: number }[]>([]);
  const [split, setSplit] = useState(50);
  const dividerRef = useRef<HTMLButtonElement>(null);
  const updateSplit = (value: number) =>
    setSplit(Math.max(0, Math.min(100, value)));
  const moveDivider = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width)
      updateSplit(
        Math.round(((event.clientX - bounds.left) / bounds.width) * 100),
      );
  };
  const dividerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const values: Record<string, number> = {
      ArrowLeft: split - 1,
      ArrowDown: split - 1,
      ArrowRight: split + 1,
      ArrowUp: split + 1,
      PageDown: split - 10,
      PageUp: split + 10,
      Home: 0,
      End: 100,
    };
    if (event.key in values) {
      event.preventDefault();
      updateSplit(values[event.key]);
    }
  };
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    if (jobState?.status === "idle" || jobState?.stage === "preparation")
      setPoints([]);
    else if (jobState?.drift_x !== undefined && jobState?.drift_y !== undefined)
      setPoints((previous) =>
        [...previous, { x: jobState.drift_x!, y: jobState.drift_y! }].slice(
          -60,
        ),
      );
  }, [jobState?.drift_x, jobState?.drift_y, jobState?.status, jobState?.stage]);
  useEffect(() => {
    setImageError(false);
    setSplit(50);
  }, [jobState?.result_path]);
  if (showcaseOnly && jobState?.result_path)
    return (
      <div className="result-content">
        <div className="result-heading">
          <div>
            <p className="eyebrow">A CLEARER PICTURE</p>
            <h2>Your night, aligned.</h2>
          </div>
          <span className="result-complete">
            <Check size={14} />
            {jobState.no_stack ? `${jobState.frame_count ?? ""} images exported` : "Trails complete"}
          </span>
        </div>
        <div
          className={`result-comparison ${jobState.first_frame_path ? "is-interactive" : ""}`}
          onPointerDown={(event) => {
            if (!jobState.first_frame_path || event.button !== 0) return;
            event.preventDefault();
            dividerRef.current?.focus({ preventScroll: true });
            event.currentTarget.setPointerCapture(event.pointerId);
            moveDivider(event);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              moveDivider(event);
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              moveDivider(event);
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
          onPointerCancel={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              event.currentTarget.releasePointerCapture(event.pointerId);
          }}
        >
          <img
            src={preview(jobState.preview_path || jobState.result_path)}
            alt={jobState.no_stack ? "First exported aligned exposure" : "Aligned star trail stack"}
            onError={() => setImageError(true)}
          />
          {jobState.first_frame_path && (
            <img
              src={preview(jobState.first_frame_path)}
              alt="Original source frame"
              style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
              onError={() => setImageError(true)}
            />
          )}
          {jobState.first_frame_path && (
            <>
              <span
                className="comparison-rule"
                style={{ left: `${split}%` }}
                aria-hidden="true"
              />
              <button
                ref={dividerRef}
                className="comparison-handle"
                style={{ left: `clamp(22px, ${split}%, calc(100% - 22px))` }}
                type="button"
                role="slider"
                aria-label="Image comparison divider"
                aria-orientation="horizontal"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={split}
                aria-valuetext={`${split}% original`}
                onKeyDown={dividerKeyDown}
              >
                <span className="comparison-pill" aria-hidden="true" />
              </button>
              <span className="comparison-label before">Original</span>
            </>
          )}
          <span className="comparison-label after">{jobState.no_stack ? "Aligned image" : "Aligned stack"}</span>
          {imageError && (
            <p className="comparison-error" role="alert">
              Preview unavailable. Download the original output below.
            </p>
          )}
        </div>
        <div className="result-footer">
          <div>
            <p>Saved to <span>{jobState.result_path}</span></p>
            {jobState.frames_dir && !jobState.no_stack && <p>Aligned images: <span>{jobState.frames_dir}</span></p>}
            {jobState.no_stack && <p>Preview shows the first exported exposure. The sequence is ready for your editing app.</p>}
            {jobState.converted_files_dir && (
              <p>Converted frames saved to <span>{jobState.converted_files_dir}</span></p>
            )}
          </div>
          <div className="result-actions">
          <a
            className="tactile-button"
            href={`${API_ORIGIN}/api/images/${jobState.no_stack ? "download-sequence" : "download"}?path=${encodeURIComponent(jobState.result_path)}`}
          >
            <ArrowDownToLine size={15} />
            {jobState.no_stack ? "Download aligned images (ZIP)" : "Download trail image"}
          </a>
          {jobState.video_path && <a className="tactile-button" href={`${API_ORIGIN}/api/images/download?path=${encodeURIComponent(jobState.video_path)}`}>
            <ArrowDownToLine size={15} /> Download trail video
          </a>}
          {!jobState.no_stack && jobState.frames_dir && <a className="tactile-button" href={`${API_ORIGIN}/api/images/download-sequence?path=${encodeURIComponent(jobState.frames_dir)}`}>
            <ArrowDownToLine size={15} /> Download aligned images (ZIP)
          </a>}
          </div>
        </div>
      </div>
    );
  const running = !!jobState && isActiveJob(jobState);
  const label = jobState?.status === "cancelling"
    ? "Cancelling alignment…"
    : jobState?.status === "cancelled"
      ? "Alignment cancelled"
      : running
    ? stages.find((stage) => stage.id === jobState.stage)?.label ||
      "Aligning frames"
    : jobState?.status === "completed"
      ? "Alignment complete"
      : jobState?.status === "failed"
        ? "Alignment stopped"
        : "Ready for your first alignment";
  const progress = Math.min(100, Math.max(0, (jobState?.progress ?? 0) * 100));
  const overall = Math.min(
    100,
    Math.max(0, (jobState?.overall_progress ?? jobState?.progress ?? 0) * 100),
  );
  const activeIndex = stages.findIndex((stage) => stage.id === jobState?.stage);
  const latest = points[points.length - 1];
  return (
    <div className="activity-content">
      <div className="activity-summary">
        <div className="activity-title">
          {running ? (
            <Loader2 size={16} className="motion-safe:animate-spin" />
          ) : (
            <Activity size={16} />
          )}
          <div>
            <strong>{label}</strong>
            <span>
              {running
                ? `${Math.round(progress)}% of this stage${jobState?.total ? ` · ${jobState.current ?? 0} / ${jobState.total} steps` : ""}${jobState?.fps ? ` · ${jobState.fps.toFixed(1)} fps` : ""}`
                : "Processing activity"}
            </span>
          </div>
        </div>
        <div className="activity-summary-end">
          {running && (
            <span className="activity-percent">
              {Math.floor(overall)}% <small>overall</small>
            </span>
          )}
          {onToggleCollapse && (
            <button
              className="activity-expand"
              onClick={onToggleCollapse}
              aria-expanded={!isCollapsed}
              aria-label={
                isCollapsed
                  ? "Show processing details"
                  : "Hide processing details"
              }
            >
              <ChevronDown
                size={16}
                style={{
                  transform: isCollapsed ? undefined : "rotate(180deg)",
                }}
              />
            </button>
          )}
        </div>
      </div>
      {running && (
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Alignment progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.floor(overall)}
        >
          <div className="progress-fill" style={{ width: `${overall}%` }} />
        </div>
      )}
      {!isCollapsed && (
        <div className="activity-details">
          {jobState?.compute && (
            <div className="compute-summary">
              <span>Processing hardware</span>
              <strong>{jobState.compute.device}{jobState.compute.backend === "opencl" ? " GPU" : ""}
                {` · ${jobState.compute.workers} CPU worker${jobState.compute.workers === 1 ? "" : "s"}`}</strong>
              {jobState.compute.fallback_reason && <small>{jobState.compute.fallback_reason}</small>}
            </div>
          )}
          <div className="pipeline-stages">
            {stages.map((stage, i) => (
              <div
                key={stage.id}
                className={
                  jobState?.status === "completed" || i < activeIndex
                    ? "done"
                    : running && i === activeIndex
                      ? "current"
                      : ""
                }
              >
                <span>
                  {jobState?.status === "completed" || i < activeIndex ? (
                    <Check size={12} />
                  ) : (
                    i + 1
                  )}
                </span>
                {stage.label}
              </div>
            ))}
          </div>
          <div className="drift-chart">
            <div className="drift-heading">
              <span>Tracking precision</span>
              <span>
                {latest
                  ? `X ${latest.x.toFixed(2)} px · Y ${latest.y.toFixed(2)} px`
                  : "Waiting for measured drift"}
              </span>
            </div>
            {points.length ? (
              <svg
                viewBox="0 0 600 80"
                preserveAspectRatio="none"
                role="img"
                aria-label="Measured horizontal and vertical star drift"
              >
                <path d="M0 40H600" stroke="#ffffff18" strokeDasharray="3 5" />
                <polyline
                  fill="none"
                  stroke="#8ec9d1"
                  strokeWidth="1.5"
                  points={points
                    .map(
                      (p, i) =>
                        `${(i * 600) / Math.max(1, points.length - 1)},${40 - p.x * 8}`,
                    )
                    .join(" ")}
                />
                <polyline
                  fill="none"
                  stroke="#ceb791"
                  strokeWidth="1.5"
                  points={points
                    .map(
                      (p, i) =>
                        `${(i * 600) / Math.max(1, points.length - 1)},${40 - p.y * 8}`,
                    )
                    .join(" ")}
                />
              </svg>
            ) : (
              <p>
                Drift measurements will appear here when star tracking begins.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
