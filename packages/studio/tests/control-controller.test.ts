import { afterEach, expect, it, vi } from "vite-plus/test";

import type { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";
import type { ControlEndpoint } from "../src/features/preview/control-sync.ts";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";

afterEach(() => {
  vi.useRealTimers();
});

const endpoint = (): ControlEndpoint => ({
  snapshot: () => [],
  subscribe: () => () => {},
  apply: vi.fn(async () => {}),
  dispose: vi.fn(),
});

it("retries a bounded control setup against the active editor session", async () => {
  vi.useFakeTimers();
  const stalled = (_support: string, _runtime: string, _session: string, signal?: AbortSignal) =>
    new Promise<never>((_resolve, reject) => {
      signal?.addEventListener(
        "abort",
        () => reject(signal.reason ?? new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  const fetchControls = vi
    .fn<typeof fetchRuntimeControls>()
    .mockImplementationOnce(stalled)
    .mockImplementationOnce(stalled)
    .mockResolvedValueOnce({
      revision: "revision-1",
      runtime: "server",
      controls: { cells: {} },
    })
    .mockResolvedValueOnce({
      revision: "revision-1",
      runtime: "wasm",
      controls: { cells: {} },
    });
  const connect = vi.fn(() => endpoint());
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.advanceTimersByTimeAsync(3_100);
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));

  expect(fetchControls).toHaveBeenCalledTimes(4);
  expect(fetchControls.mock.calls.map((call) => call[2])).toEqual([
    "s_editor1",
    "s_editor1",
    "s_editor1",
    "s_editor1",
  ]);
  expect(status).toHaveBeenLastCalledWith({ phase: "ready" }, "revision-1", undefined);
  controller.stop();
});

it("reports exhausted control setup and clears it after recovery", async () => {
  vi.useFakeTimers();
  let available = false;
  const connect = vi.fn(() => (available ? endpoint() : undefined));
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async (_support, runtime) => ({
    revision: "revision-1",
    runtime,
    controls: { cells: {} },
  }));
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.runAllTimersAsync();
  expect(status.mock.calls.at(-1)?.[0]).toMatchObject({ phase: "degraded" });

  available = true;
  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(status.mock.calls.at(-1)?.[0]).toEqual({ phase: "ready" }));

  controller.stop();
});

it("discards a superseded control read after its response settles", async () => {
  type Snapshot = Awaited<ReturnType<typeof fetchRuntimeControls>>;
  let resolveRead!: (value: Snapshot) => void;
  const pending = new Promise<Snapshot>((resolve) => {
    resolveRead = resolve;
  });
  const signals: AbortSignal[] = [];
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, runtime, _session, signal) => {
      if (signal) {
        signals.push(signal);
      }
      return { ...(await pending), runtime };
    },
  );
  const connect = vi.fn(() => endpoint());
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    connectPreview: connect,
    fetchControls,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(2));
  controller.stop();
  expect(signals.every((signal) => !signal.aborted)).toBe(true);
  resolveRead({ revision: "revision-1", runtime: "server", controls: { cells: {} } });
  await pending;
  await Promise.resolve();

  expect(connect).not.toHaveBeenCalled();
});

it("ignores a rejected control read after its view stops loading", async () => {
  vi.useFakeTimers();
  type Snapshot = Awaited<ReturnType<typeof fetchRuntimeControls>>;
  let rejectRead!: (error: Error) => void;
  const pending = new Promise<Snapshot>((_resolve, reject) => {
    rejectRead = reject;
  });
  const signals: AbortSignal[] = [];
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, _runtime, _session, signal) => {
      if (signal) {
        signals.push(signal);
      }
      return await pending;
    },
  );
  const connect = vi.fn(() => endpoint());
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(2));
  controller.stop();
  expect(signals.every((signal) => !signal.aborted)).toBe(true);
  rejectRead(new Error("control read failed"));
  await expect(pending).rejects.toThrow("control read failed");
  await Promise.resolve();
  await vi.runAllTimersAsync();

  expect(fetchControls).toHaveBeenCalledTimes(2);
  expect(connect).not.toHaveBeenCalled();
  expect(status).not.toHaveBeenCalled();
});

it("ignores a loading attempt timeout after its view stops", async () => {
  vi.useFakeTimers();
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, _runtime, _session, signal) =>
      await new Promise<never>((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(signal.reason ?? new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
  );
  const connect = vi.fn(() => endpoint());
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(2));
  controller.stop();
  await vi.advanceTimersByTimeAsync(3_100);
  await vi.runAllTimersAsync();

  expect(fetchControls).toHaveBeenCalledTimes(2);
  expect(connect).not.toHaveBeenCalled();
  expect(status).not.toHaveBeenCalled();
});
