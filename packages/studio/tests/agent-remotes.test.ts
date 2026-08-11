import { afterEach, expect, it, vi } from "vite-plus/test";

import { createViewActivationRemote } from "../src/app/activation-remote.ts";
import { createBrowserObservationRemote } from "../src/features/preview/observation-remote.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

const jsonRequestBody = (init?: RequestInit): Record<string, unknown> => {
  const body = init?.body;
  expect(typeof body).toBe("string");
  return JSON.parse(body as string) as Record<string, unknown>;
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("uploads browser observations in monotonic order within one request", async () => {
  const first = deferred<Response>();
  const fetch = vi
    .fn()
    .mockImplementationOnce(() => first.promise)
    .mockResolvedValue(new Response(null, { status: 204 }));
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
  };

  const firstUpload = record({ ...observation, state: "loading" });
  const secondUpload = record(observation);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

  first.resolve(new Response(null, { status: 204 }));
  await Promise.all([firstUpload, secondUpload]);

  const payloads = fetch.mock.calls.map(([, init]) => {
    const body = (init as RequestInit).body;
    expect(typeof body).toBe("string");
    return JSON.parse(body as string);
  });
  expect(payloads.map((payload) => payload.sequence)).toEqual([0, 1]);
  expect(payloads.map((payload) => payload.requestId)).toEqual([
    "request-dashboard",
    "request-dashboard",
  ]);
  expect(payloads.map((payload) => payload.state)).toEqual(["loading", "ready"]);
});

it("retries a transient observation upload with the same sequence", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("network unavailable"))
    .mockResolvedValue(new Response(null, { status: 204 }));
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
  };

  await record(observation);

  expect(fetch).toHaveBeenCalledTimes(2);
  const sequences = fetch.mock.calls.map(
    ([, init]) => jsonRequestBody(init as RequestInit).sequence,
  );
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
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    const body = jsonRequestBody(init);
    if (body.requestId !== "expired-request") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () =>
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
  };
  const expired = record({ ...base, requestId: "expired-request" });
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const fresh = record({ ...base, requestId: "fresh-request" });

  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  await Promise.all([expired, fresh]);
  expect(fetch.mock.calls.map(([, init]) => jsonRequestBody(init).requestId)).toEqual([
    "expired-request",
    "fresh-request",
  ]);
});

it("a stalled loading upload yields promptly to terminal evidence", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn((_url: string, init?: RequestInit) => {
    const body = jsonRequestBody(init);
    if (body.state === "ready") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () =>
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
  };
  const loading = record({ ...base, state: "loading" });
  const loadingResult = expect(loading).rejects.toMatchObject({
    code: "browser-observation-upload-timeout",
  });
  const ready = record({ ...base, state: "ready" });

  await vi.advanceTimersByTimeAsync(800);
  await loadingResult;
  await ready;

  expect(fetch).toHaveBeenCalledTimes(2);
  expect(jsonRequestBody(fetch.mock.calls[1]?.[1]).state).toBe("ready");
});

it("acknowledges an activation with its browser identity", async () => {
  const fetch = vi.fn(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  await acknowledge(9, "report", new AbortController().signal);

  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/_marimo-studio/activations/9/ack"),
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        schema: 1,
        clientId: "browser-client-1234",
        view: "report",
      }),
    }),
  );
});

it("retries a stalled activation acknowledgement with the same generation", async () => {
  vi.useFakeTimers();
  const fetch = vi
    .fn()
    .mockImplementationOnce((_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    })
    .mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const acknowledged = acknowledge(11, "report", new AbortController().signal);
  await vi.advanceTimersByTimeAsync(1_100);
  await acknowledged;

  expect(fetch).toHaveBeenCalledTimes(2);
  expect(
    fetch.mock.calls.every(([url]) => url.includes("/_marimo-studio/activations/11/ack")),
  ).toBe(true);
  expect(fetch.mock.calls.map(([, init]) => jsonRequestBody(init).schema)).toEqual([1, 1]);
  expect(fetch.mock.calls.map(([, init]) => jsonRequestBody(init).view)).toEqual([
    "report",
    "report",
  ]);
});
