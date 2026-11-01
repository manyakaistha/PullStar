import { Check, Loader2, AlertCircle, Layers } from "lucide-react";
import type { JobState } from "./LiveTelemetry";
import { isActiveJob } from "../jobAction";

export type WorkspaceView = "workspace" | "results";
interface WorkspaceNavProps {
  activeView: WorkspaceView;
  onSelectView: (view: WorkspaceView) => void;
  hasResult: boolean;
  jobState: JobState;
}

export function WorkspaceNav({
  activeView,
  onSelectView,
  hasResult,
  jobState,
}: WorkspaceNavProps) {
  const running = isActiveJob(jobState);
  const status = jobState.status === "cancelling"
    ? "Cancelling…"
    : jobState.status === "cancelled"
      ? "Alignment cancelled"
      : running
    ? `Aligning · ${Math.floor((jobState.overall_progress ?? jobState.progress ?? 0) * 100)}%`
    : jobState.status === "completed"
      ? "Alignment complete"
      : jobState.status === "failed"
        ? "Needs attention"
        : "Local workspace";
  return (
    <header className="studio-header">
      <div className="studio-brand">
        <img className="brand-app-icon" src={`${import.meta.env.BASE_URL}app-icon.svg`} alt="" width={40} height={40} />
        <span>
          <strong>
            PullStar<span className="brand-period">.</span>
          </strong>
          <small>THE NIGHT, IN FOCUS</small>
        </span>
      </div>
      {hasResult && (
        <nav
          className="studio-navigation glass-surface glass-nav"
          aria-label="Workspace views"
        >
          <button
            className="nav-pill"
            aria-pressed={activeView === "workspace"}
            onClick={() => onSelectView("workspace")}
          >
            <Layers size={14} aria-hidden="true" />
            Workspace
          </button>
          <button
            className="nav-pill"
            aria-pressed={activeView === "results"}
            onClick={() => onSelectView("results")}
          >
            <Check size={14} aria-hidden="true" />
            Results
          </button>
        </nav>
      )}
      <div className={`studio-status ${jobState.status}`} role="status">
        {running ? (
          <Loader2
            size={14}
            className="motion-safe:animate-spin"
            aria-hidden="true"
          />
        ) : jobState.status === "failed" ? (
          <AlertCircle size={14} aria-hidden="true" />
        ) : (
          <span className="status-dot" />
        )}
        <span>{status}</span>
      </div>
    </header>
  );
}
