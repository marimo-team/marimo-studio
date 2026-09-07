import { afterEach, expect, it, vi } from "vite-plus/test";

import type { fetchRuntimeControls } from "../src/features/preview/control-remote.ts";
import type { FrameControlEndpoint } from "../src/features/preview/frame-bridge.ts";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";

afterEach(() => {
  vi.useRealTimers();
});

const endpoint = (): FrameControlEndpoint => ({
  metadata: () => ({ cells: {} }),
  snapshot: () => [],
  subscribe: () => () => {},
  apply: vi.fn(async () => {}),
  dispose: vi.fn(),
});

it("waits for runtime control metadata before synchronizing the editor value", async () => {
  vi.useFakeTimers();
  let available = false;
  const preview = {
    ...endpoint(),
    metadata: () => (available ? { cells: { scale: "wasm-control" } } : undefined),
    snapshot: () => [{ objectId: "wasm-control-0", value: 2 }],
  };
  const editor = {
    ...endpoint(),
    snapshot: () => [{ objectId: "live-control-0", value: 3 }],
  };
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async () => ({
    revision: "revision-1",
    controls: { cells: { scale: "live-control" } },
  }));
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    clientId: () => "browser-client-1234",
    connect: () => editor,
    connectPreview: () => preview,
    fetchControls,
  });
  controller.begin("revision-1", undefined, "s_editor1");
  expect(fetchControls).not.toHaveBeenCalled();
  available = true;
  await vi.advanceTimersByTimeAsync(100);
  expect(preview.apply).toHaveBeenCalledWith([{ objectId: "wasm-control-0", value: 3 }]);
  expect(fetchControls).toHaveBeenCalledOnce();
  controller.stop();
});

it("retries a bounded control setup against the active editor session", async () => {
  vi.useFakeTimers();
  const stalled = (
    _support: string,
    _runtime: string,
    _session: string,
    _revision: string,
    signal?: AbortSignal,
  ) =>
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
    .mockResolvedValueOnce({
      revision: "revision-1",
      controls: { cells: {} },
    });
  const connect = vi.fn(() => endpoint());
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    clientId: () => "browser-client-1234",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.advanceTimersByTimeAsync(3_100);
  await vi.waitFor(() =>
    expect(status).toHaveBeenLastCalledWith({ phase: "ready" }, "revision-1", undefined),
  );

  expect(fetchControls).toHaveBeenCalledTimes(2);
  expect(fetchControls.mock.calls.every(([, , sessionId]) => sessionId === "s_editor1")).toBe(true);
  expect(status).toHaveBeenLastCalledWith({ phase: "ready" }, "revision-1", undefined);
  controller.stop();
});

it("reports exhausted control setup and clears it after recovery", async () => {
  vi.useFakeTimers();
  let available = false;
  const connect = vi.fn(() => (available ? endpoint() : undefined));
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(async () => ({
    revision: "revision-1",
    controls: { cells: {} },
  }));
  const status = vi.fn();
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    clientId: () => "browser-client-1234",
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
    async (_support, _client, _session, _revision, signal) => {
      if (signal) {
        signals.push(signal);
      }
      return await pending;
    },
  );
  const connect = vi.fn(() => endpoint());
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    clientId: () => "browser-client-1234",
    connect,
    connectPreview: connect,
    fetchControls,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(1));
  controller.stop();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
  resolveRead({ revision: "revision-1", controls: { cells: {} } });
  await pending;
  await Promise.resolve();

  expect(connect).toHaveBeenCalledOnce();
});

it("ignores a loading attempt timeout after its view stops", async () => {
  vi.useFakeTimers();
  const fetchControls = vi.fn<typeof fetchRuntimeControls>(
    async (_support, _client, _session, _revision, signal) =>
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
    clientId: () => "browser-client-1234",
    connect,
    connectPreview: connect,
    fetchControls,
    status,
  });

  controller.begin("revision-1", undefined, "s_editor1");
  await vi.waitFor(() => expect(fetchControls).toHaveBeenCalledTimes(1));
  controller.stop();
  await vi.advanceTimersByTimeAsync(3_100);
  await vi.runAllTimersAsync();

  expect(fetchControls).toHaveBeenCalledTimes(1);
  expect(connect).toHaveBeenCalledOnce();
  expect(status).not.toHaveBeenCalled();
});
