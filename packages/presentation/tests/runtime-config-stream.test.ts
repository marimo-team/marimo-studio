import type { RuntimeProgress } from "@marimo-studio/protocol/runtime-progress";

import { afterEach, expect, test, vi } from "vite-plus/test";

import { fetchRuntimeConfig, RuntimeConfigRequestError } from "../src/runtime-config/index.ts";
import { runtimeProgress, RuntimeProgressStore } from "../src/runtime-config/progress.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

const encoder = new TextEncoder();
const headers = { "content-type": "application/x-ndjson" };
globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

afterEach(() => vi.unstubAllGlobals());

test("reports streamed work before configuration completes and releases the reader", async () => {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(stream) {
      controller = stream;
    },
    cancel: cancelled,
  });
  const response = new Response(body, { headers });
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetch);
  const updates: (RuntimeProgress | null)[] = [];
  let reported!: () => void;
  const firstProgress = new Promise<void>((resolve) => {
    reported = resolve;
  });
  const unsubscribe = runtimeProgress.subscribe(({ progress }) => {
    updates.push(progress);
    if (progress) reported();
  });
  try {
    const configuration = fetchRuntimeConfig("/_marimo-studio/views/dashboard");
    const packet = encoder.encode(
      JSON.stringify({
        type: "progress",
        progress: { message: "Préparing states", completed: 2, total: 7 },
      }) + "\n",
    );
    for (const byte of packet) controller.enqueue(Uint8Array.of(byte));
    await firstProgress;
    expect(updates.at(-1)).toEqual({ message: "Préparing states", completed: 2, total: 7 });
    expect(new Headers(fetch.mock.calls[0]?.[1]?.headers).get("Accept")).toBe(
      "application/x-ndjson",
    );
    controller.enqueue(
      encoder.encode(JSON.stringify({ type: "config", config: runtimeConfig() }) + "\n"),
    );
    controller.close();
    await expect(configuration).resolves.toEqual(runtimeConfig());
    expect(updates.at(-1)).toBeNull();
    expect(cancelled).not.toHaveBeenCalled();
    expect(response.body?.locked).toBe(false);
  } finally {
    unsubscribe();
  }
});

test("preserves streamed error details after successful HTTP headers", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "error",
          error: "runtime-sync-pending",
          message: "Waiting for the current notebook.",
          hint: "Keep this preview open.",
          transient: true,
          context: { state: "baseline", attempts: 2 },
          revision: 42,
        }) + "\n",
        { headers },
      ),
    ),
  );
  await expect(fetchRuntimeConfig("/_marimo-studio/views/dashboard")).rejects.toMatchObject({
    code: "runtime-sync-pending",
    message: "Waiting for the current notebook.",
    hint: "Keep this preview open.",
    transient: true,
    details: { context: { state: "baseline", attempts: 2 } },
  });
});

test.each([
  ["truncated", JSON.stringify({ type: "progress", progress: { message: "Preparing" } }) + "\n"],
  ["malformed JSON", "{broken}\n"],
  [
    "incomplete UTF-8 after configuration",
    Uint8Array.from([
      ...encoder.encode(JSON.stringify({ type: "config", config: runtimeConfig() }) + "\n"),
      0xc3,
    ]),
  ],
  [
    "invalid counts",
    JSON.stringify({
      type: "progress",
      progress: { message: "Preparing", completed: 3, total: 2 },
    }) + "\n",
  ],
  ["oversized", " ".repeat(16 * 1_024 * 1_024 + 65_537)],
])("rejects a %s configuration stream", async (_name, body) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers })));
  await expect(fetchRuntimeConfig("/_marimo-studio/views/dashboard")).rejects.toBeInstanceOf(
    RuntimeConfigRequestError,
  );
});

test("cancels a pending stream when its request is aborted", async () => {
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({ cancel: cancelled });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers })));
  const lifetime = new AbortController();
  const configuration = fetchRuntimeConfig("/_marimo-studio/views/dashboard", lifetime.signal);
  const failure = expect(configuration).rejects.toMatchObject({ name: "AbortError" });
  await Promise.resolve();
  lifetime.abort();
  await failure;
  expect(cancelled).toHaveBeenCalled();
});

test("retired progress cannot update or clear its successor", () => {
  const progress = new RuntimeProgressStore();
  const updates = vi.fn();
  const unsubscribe = progress.subscribe(updates);
  const first = progress.begin("server", "/first/config", "revision-1");
  const second = progress.begin("custom-runtime", "/second/config", "revision-2");
  second.report({ message: "Loading model", completed: 4, total: 8 });
  updates.mockClear();
  first.report({ message: "Old work", completed: 1, total: 2 });
  first.close();
  expect(updates).not.toHaveBeenCalled();
  second.close();
  expect(updates).toHaveBeenCalledExactlyOnceWith({
    runtime: "custom-runtime",
    supportUrl: "/second/config",
    revision: "revision-2",
    progress: null,
  });
  unsubscribe();
});

test("retries configuration after its response stream disconnects", async () => {
  const { fetchRuntimeConfigWithRetry } = await import("../src/runtime-config/index.ts");
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(stream) {
      controller = stream;
    },
  });
  const fetch = vi
    .fn<typeof globalThis.fetch>()
    .mockResolvedValueOnce(new Response(body, { headers }))
    .mockResolvedValueOnce(Response.json(runtimeConfig()));
  vi.stubGlobal("fetch", fetch);
  let reported!: () => void;
  const received = new Promise<void>((resolve) => {
    reported = resolve;
  });
  const unsubscribe = runtimeProgress.subscribe(({ progress }) => {
    if (progress) reported();
  });
  try {
    const request = fetchRuntimeConfigWithRetry("/_marimo-studio/views/dashboard");
    controller.enqueue(
      encoder.encode(
        JSON.stringify({ type: "progress", progress: { message: "Preparing" } }) + "\n",
      ),
    );
    await received;
    controller.error(new TypeError("Connection closed"));
    await expect(request).resolves.toEqual(runtimeConfig());
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    unsubscribe();
  }
});
