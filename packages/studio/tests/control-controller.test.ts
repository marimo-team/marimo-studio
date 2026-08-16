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
  const controller = new PreviewControlController({
    runtime: "wasm",
    editor: document.createElement("iframe"),
    preview: document.createElement("iframe"),
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    fetchControls,
  });

  controller.begin("revision-1", "s_123456");
  await vi.advanceTimersByTimeAsync(3_100);
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));

  expect(fetchControls).toHaveBeenCalledTimes(4);
  expect(fetchControls.mock.calls.map((call) => call[2])).toEqual([
    "s_123456",
    "s_123456",
    "s_123456",
    "s_123456",
  ]);
  controller.stop();
});
