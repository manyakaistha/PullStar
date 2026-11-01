import { test } from "node:test";
import assert from "node:assert/strict";
import { JobAction, type JobState } from "../src/jobAction.js";

const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
};

test("cancelling before creation responds still cancels the server worker", { timeout: 2000 }, async () => {
  const creation = deferred<Response>();
  const updates: JobState[] = [];
  let cancelled = false;
  let creationSignal: AbortSignal | null | undefined;
  const fetcher: typeof fetch = async (url, init) => {
    if (String(url) === "/api/jobs") { creationSignal = init?.signal; return creation.promise; }
    if (String(url).endsWith("/cancel")) { cancelled = true; return response({ status: "cancelled" }); }
    return response({ status: cancelled ? "cancelled" : "running" });
  };
  const action = new JobAction("", (state) => updates.push(state), fetcher, 0);
  const completion = action.start("/api/jobs", {});
  action.cancel();
  assert.equal(updates.at(-1)?.status, "cancelling");
  assert.equal(action.active, true);
  assert.equal(creationSignal, undefined);
  creation.resolve(response({ job_id: "one" }));
  assert.equal((await completion).status, "cancelled");
  assert.equal(cancelled, true);
  assert.equal(action.active, false);
});

test("an accepted cancel remains busy until the worker confirms it stopped", { timeout: 2000 }, async () => {
  const accepted = deferred<void>();
  let stopped = false;
  const updates: JobState[] = [];
  const fetcher: typeof fetch = async (url) => {
    if (String(url) === "/api/jobs") return response({ job_id: "one" });
    if (String(url).endsWith("/cancel")) { accepted.resolve(); return response({ status: "cancelling" }); }
    return response({ status: stopped ? "cancelled" : "running" });
  };
  const action = new JobAction("", (state) => updates.push(state), fetcher, 0);
  const completion = action.start("/api/jobs", {});
  action.cancel();
  action.cancel();
  await accepted.promise;
  assert.equal(action.active, true);
  assert.equal(updates.at(-1)?.status, "cancelling");
  stopped = true;
  await completion;
  assert.equal(updates.at(-1)?.status, "cancelled");
});

test("failed cancellation leaves Cancel available and can be retried", { timeout: 2000 }, async () => {
  let calls = 0;
  let stopped = false;
  const updates: JobState[] = [];
  const fetcher: typeof fetch = async (url) => {
    if (String(url) === "/api/jobs") return response({ job_id: "one" });
    if (String(url).endsWith("/cancel")) {
      if (++calls === 1) return response({ detail: "Unavailable" }, 503);
      stopped = true;
      return response({ status: "cancelled" });
    }
    return response({ status: stopped ? "cancelled" : "running" });
  };
  const action = new JobAction("", (state) => {
    updates.push(state);
    if (state.error?.includes("Cancellation could not be confirmed")) {
      assert.equal(action.active, true);
      assert.ok(["created", "running"].includes(state.status));
      action.cancel();
    }
  }, fetcher, 0);
  const completion = action.start("/api/jobs", {});
  action.cancel();
  assert.equal((await completion).status, "cancelled");
  assert.equal(calls, 2);
  assert.ok(updates.some((state) => state.error));
});

test("network loss does not claim that the worker stopped", { timeout: 2000 }, async () => {
  let polls = 0;
  const fetcher: typeof fetch = async (url) => {
    if (String(url) === "/api/jobs") return response({ job_id: "one" });
    if (String(url).endsWith("/cancel")) return response({ status: "cancelled" });
    if (++polls === 1) throw new TypeError("offline");
    return response({ status: "cancelled" });
  };
  const action = new JobAction("", (state) => {
    if (state.error?.includes("Connection lost")) {
      assert.equal(action.active, true);
      action.cancel();
    }
  }, fetcher, 0);
  assert.equal((await action.start("/api/jobs", {})).status, "cancelled");
});

test("disposing while creation is pending stops work and suppresses stale UI updates", { timeout: 2000 }, async () => {
  const creation = deferred<Response>();
  const updates: JobState[] = [];
  let cancelled = false;
  const fetcher: typeof fetch = async (url) => {
    if (String(url) === "/api/stars/detect/start") return creation.promise;
    if (String(url).endsWith("/cancel")) cancelled = true;
    return response({ status: cancelled ? "cancelled" : "running" });
  };
  const action = new JobAction("", (state) => updates.push(state), fetcher, 0);
  const completion = action.start("/api/stars/detect/start", {});
  action.dispose();
  creation.resolve(response({ job_id: "old-folder" }));
  await completion;
  assert.equal(cancelled, true);
  assert.equal(updates.length, 1);
  assert.equal(updates[0].status, "created");
});

test("a late running poll cannot overwrite a completed cancellation response", { timeout: 2000 }, async () => {
  const polling = deferred<void>();
  const oldResponse = deferred<Response>();
  const updates: JobState[] = [];
  const fetcher: typeof fetch = async (url) => {
    if (String(url) === "/api/jobs") return response({ job_id: "one" });
    if (String(url).endsWith("/cancel")) {
      oldResponse.resolve(response({ status: "running" }));
      return response({ status: "cancelled" });
    }
    polling.resolve();
    return oldResponse.promise;
  };
  const action = new JobAction("", (state) => updates.push(state), fetcher, 0);
  const completion = action.start("/api/jobs", {});
  await polling.promise;
  action.cancel();
  assert.equal((await completion).status, "cancelled");
  assert.equal(updates.at(-1)?.status, "cancelled");
});

test("creation failure returns an idle worker state with the service's error", async () => {
  const fetcher: typeof fetch = async () => response({ detail: "No source folder" }, 400);
  const action = new JobAction("", () => {}, fetcher, 0);
  const result = await action.start("/api/jobs", {});
  assert.equal(result.status, "failed");
  assert.equal(result.error, "No source folder");
  assert.equal(action.active, false);
});

test("native browser fetch is called with the global receiver", async () => {
  const fetcher: typeof fetch = async function (this: unknown, url) {
    assert.equal(this, globalThis);
    return response(String(url) === "/api/jobs" ? { job_id: "bound" } : { status: "completed" });
  };
  const action = new JobAction("", () => {}, fetcher, 0);
  assert.equal((await action.start("/api/jobs", {})).status, "completed");
});


test("validation errors explain the setting instead of displaying an object", async () => {
  const action = new JobAction("", () => {}, async () => response({detail: [{msg: "ProRes requires MOV"}]}, 422));
  const state = await action.start("/api/jobs", {});
  assert.equal(state.status, "failed");
  assert.equal(state.error, "ProRes requires MOV");
});
