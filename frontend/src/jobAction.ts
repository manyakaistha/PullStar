export interface DetectionResult {
  reference_image: string;
  reference_stars: [number, number][];
  second_star?: [number, number];
  confidence: number;
}

export interface JobState {
  id?: string;
  status: "idle" | "created" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  stage?: "preparation" | "conversion" | "pass1" | "crop_calc" | "pass2" | "video_render" | "done";
  conversion_format?: "none" | "jpg" | "tiff";
  converted_files_dir?: string | null;
  video_enabled?: boolean;
  progress?: number;
  overall_progress?: number;
  current?: number;
  total?: number;
  drift_x?: number;
  drift_y?: number;
  fps?: number;
  result_path?: string | null;
  no_stack?: boolean;
  frames_dir?: string;
  frame_count?: number;
  preview_path?: string;
  video_path?: string;
  error?: string | null;
  first_frame_path?: string;
  live_preview_path?: string | null;
  live_preview_revision?: number;
  result?: DetectionResult;
  compute?: { backend: string; device: string; workers: number; fallback_reason?: string };
}

export const isActiveJob = (job: JobState) =>
  ["created", "running", "cancelling"].includes(job.status);
const terminal = (job: JobState) =>
  ["completed", "cancelled", "failed"].includes(job.status);

class RequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** One action owns its server job until the server confirms a terminal state. */
export class JobAction {
  private jobId: string | null = null;
  private cancelRequested = false;
  private cancelError = "";
  private disposed = false;
  private started = false;
  private serverState: JobState = { status: "created", stage: "preparation" };
  private state: JobState = this.serverState;
  active = false;

  constructor(
    privateOrigin: string,
    onUpdate: (job: JobState) => void,
    fetcher: typeof fetch = fetch,
    pollMilliseconds = 250,
  ) {
    this.origin = privateOrigin;
    this.onUpdate = onUpdate;
    this.fetcher = fetcher.bind(globalThis);
    this.pollMilliseconds = pollMilliseconds;
  }
  private origin: string;
  private onUpdate: (job: JobState) => void;
  private fetcher: typeof fetch;
  private pollMilliseconds: number;

  private async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await this.fetcher(`${this.origin}${path}`, body === undefined ? undefined : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      const message = typeof detail === "string" ? detail
        : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg || "Invalid setting").join("; ")
        : "The action request failed.";
      throw new RequestError(message, response.status);
    }
    return data;
  }

  private update(job: JobState, connectionError = "") {
    // A late poll must never revive a cancelled/completed action.
    if (terminal(this.state)) return;
    this.serverState = job;
    this.state = {
      ...job,
      status: this.cancelRequested && !terminal(job) ? "cancelling" : job.status,
      error: terminal(job) ? job.error : this.cancelError || connectionError || job.error,
    };
    if (terminal(this.state)) this.active = false;
    if (!this.disposed) this.onUpdate(this.state);
  }

  async start(path: string, payload: unknown): Promise<JobState> {
    if (this.started) throw new Error("Create a new action to start another job.");
    this.started = true;
    this.active = true;
    this.update(this.serverState);
    try {
      // Do not abort creation: its response identifies the worker that must stop.
      const created = await this.request<{ job_id: string }>(path, payload);
      if (!created.job_id) throw new Error("The service did not return an action ID.");
      this.jobId = created.job_id;
      if (this.cancelRequested) void this.sendCancellation();
      while (!terminal(this.state)) {
        try {
          this.update(await this.request<JobState>(`/api/jobs/${this.jobId}`));
        } catch (error) {
          if (error instanceof RequestError && error.status === 404) throw error;
          // A dropped connection is not confirmation that a worker has stopped.
          this.update(this.serverState, "Connection lost. Waiting for the action status; you can retry cancellation.");
        }
        if (!terminal(this.state))
          await new Promise((resolve) => setTimeout(resolve, this.pollMilliseconds));
      }
    } catch (error) {
      this.update({ status: "failed", error: error instanceof Error ? error.message : "Unable to start the action." });
    }
    return this.state;
  }

  cancel() {
    if (!this.active || this.cancelRequested) return;
    this.cancelRequested = true;
    this.cancelError = "";
    this.update(this.serverState);
    if (this.jobId) void this.sendCancellation();
  }

  private async sendCancellation() {
    try {
      this.update(await this.request<JobState>(`/api/jobs/${this.jobId}/cancel`, {}));
    } catch {
      this.cancelRequested = false;
      this.cancelError = "Cancellation could not be confirmed. Press Cancel to try again.";
      this.update(this.serverState);
    }
  }

  dispose() {
    this.disposed = true;
    this.cancel();
  }
}
