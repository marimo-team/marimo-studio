import {
  browserObservationSchema,
  type BrowserObservation,
} from "@marimo-studio/protocol/browser-observations";
import { afterEach, expect, it, vi } from "vite-plus/test";

import { createBrowserObservationRemote } from "../src/features/preview/observation-remote.ts";
import { deferred, type JsonFetch, type JsonRequestInit } from "./agent-remote-test-support.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";

const observationRequestBody = (init: JsonRequestInit): BrowserObservation =>
  browserObservationSchema.parse(JSON.parse(init.body));

const runtimeStatus = (phase: "ready" | "synchronizing" = "ready") => ({
  runtime: "server",
  view: "dashboard",
  revision: "revision-dashboard",
  sessionId: "s_123456",
  current: { phase, diagnostics: [] },
  transitions: [
    {
      sequence: 0,
      observedAt: 1_000,
      revision: "revision-dashboard",
      sessionId: "s_123456",
      phase,
      diagnostics: [],
      diagnosticsTruncated: false,
    },
  ],
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("uploads browser observations in monotonic order within one request", async () => {
  const first = deferred<Response>();
  const fetch = vi.fn<JsonFetch>();
  fetch.mockImplementationOnce(() => first.promise);
  fetch.mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const record = createBrowserObservationRemote(
    (view) => `/_marimo-studio/views/${view}`,
    "server-token",
    "browser-client-1234",
  );
  const observation = {
    view: "dashboard",
    runtime: "server",
    revision: "revision-dashboard",
    state: "ready" as const,
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    requestId: "request-dashboard",
    query: "region=emea",
    ...emptyProjectionEvidence,
    runtimeStatus: runtimeStatus(),
  };

  const firstUpload = record({
    ...observation,
    state: "loading",
    runtimeStatus: runtimeStatus("synchronizing"),
  });
  const secondUpload = record(observation);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

  first.resolve(new Response(null, { status: 204 }));
  await Promise.all([firstUpload, secondUpload]);

  const payloads = fetch.mock.calls.map(([, init]) => observationRequestBody(init));
  expect(payloads.map((payload) => payload.sequence)).toEqual([0, 1]);
  expect(payloads.map((payload) => payload.state)).toEqual(["loading", "ready"]);
});

it("retries a transient observation upload with the same sequence", async () => {
  const fetch = vi.fn<JsonFetch>();
  fetch.mockRejectedValueOnce(new TypeError("network unavailable"));
  fetch.mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const record = createBrowserObservationRemote(
    (view) => `/_marimo-studio/views/${view}`,
    "server-token",
    "browser-client-1234",
  );
  const observation = {
    view: "dashboard",
    runtime: "server",
    revision: "revision-dashboard",
    state: "ready" as const,
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    requestId: "request-dashboard",
    query: "",
    ...emptyProjectionEvidence,
    runtimeStatus: runtimeStatus(),
  };

  await record(observation);

  expect(fetch).toHaveBeenCalledTimes(2);
  const sequences = fetch.mock.calls.map(([, init]) => observationRequestBody(init).sequence);
  expect(sequences).toEqual([0, 0]);
});

it("does not retry a rejected observation request", async () => {
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ error: "browser-observation-rejected" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const record = createBrowserObservationRemote(
    (view) => `/_marimo-studio/views/${view}`,
    "server-token",
    "browser-client-1234",
  );

  const rejected = record({
    view: "dashboard",
    runtime: "server",
    revision: "revision-dashboard",
    state: "ready",
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    requestId: "expired-request",
    query: "",
    ...emptyProjectionEvidence,
    runtimeStatus: runtimeStatus(),
  });

  await expect(rejected).rejects.toMatchObject({
    status: 409,
    code: "browser-observation-rejected",
    retryable: false,
  });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("a new request supersedes a stalled upload before its retry budget", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn((_url: string, init: JsonRequestInit) => {
    const body = observationRequestBody(init);
    if (body.requestId !== "expired-request") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  });
  vi.stubGlobal("fetch", fetch);
  const record = createBrowserObservationRemote(
    (view) => `/_marimo-studio/views/${view}`,
    "server-token",
    "browser-client-1234",
  );
  const base = {
    view: "dashboard",
    runtime: "server",
    revision: "revision-dashboard",
    state: "ready" as const,
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    query: "",
    ...emptyProjectionEvidence,
    runtimeStatus: runtimeStatus(),
  };
  const expired = record({ ...base, requestId: "expired-request" });
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const fresh = record({ ...base, requestId: "fresh-request" });

  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  await Promise.all([expired, fresh]);
});

it("a stalled loading upload yields promptly to terminal evidence", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn((_url: string, init: JsonRequestInit) => {
    const body = observationRequestBody(init);
    if (body.state === "ready") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      );
    });
  });
  vi.stubGlobal("fetch", fetch);
  const record = createBrowserObservationRemote(
    (view) => `/_marimo-studio/views/${view}`,
    "server-token",
    "browser-client-1234",
  );
  const base = {
    view: "dashboard",
    runtime: "server",
    revision: "revision-dashboard",
    diagnostics: [],
    runtimeInstance: "runtime-instance",
    sessionId: "s_123456",
    requestId: "request-dashboard",
    query: "",
    ...emptyProjectionEvidence,
    runtimeStatus: runtimeStatus(),
  };
  const loading = record({
    ...base,
    state: "loading",
    runtimeStatus: runtimeStatus("synchronizing"),
  });
  const loadingResult = expect(loading).rejects.toMatchObject({
    code: "browser-observation-upload-timeout",
  });
  const ready = record({ ...base, state: "ready" });

  await vi.advanceTimersByTimeAsync(800);
  await loadingResult;
  await ready;

  expect(fetch).toHaveBeenCalledTimes(2);
});
