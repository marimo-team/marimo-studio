import { afterEach, expect, it, vi } from "vite-plus/test";

import type { PreviewController } from "../src/features/preview/controller.ts";

import { controller, dispatchPreviewMessage, frame } from "./preview-test-support.ts";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.body.replaceChildren();
});

it("rejects initial-document messages and pagehide after a reload", () => {
  const editor = frame("loading");
  const preview = frame("complete");
  const report = vi.fn();
  const server = controller(
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    report,
  );
  expect(preview.dataset.previewLifecycleId).toBe("1");
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision:initial",
  });
  expect(server.runtimeStatus().current.phase).toBe("ready");

  server.presentationBaseline("revision:initial");
  server.presentationBaseline(null);
  server.reload();
  const currentLifecycleId = Number(
    new URL(preview.src).searchParams.get("marimo_studio_lifecycle"),
  );
  expect(currentLifecycleId).toBeGreaterThan(1);
  expect(preview.dataset.previewLifecycleId).toBe(String(currentLifecycleId));
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision:stale",
  });
  expect(server.runtimeStatus().current.phase).toBe("connecting");
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: currentLifecycleId,
    view: "dashboard",
    revision: "revision:current",
  });
  dispatchPreviewMessage(null, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
  });

  expect(server.runtimeStatus()).toMatchObject({
    revision: "revision:current",
    current: { phase: "ready" },
  });
  expect(report.mock.calls.at(-1)?.[0]).toMatchObject({ lifecycleId: currentLifecycleId });
  server.dispose();
});

it("restores a ready presentation when a failed transaction retries unchanged", async () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = {
    postMessage: vi.fn(
      (message: { type?: string; generation?: number }, _target: string, ports?: MessagePort[]) => {
        if (message.type === "marimo-studio:presentation-refresh-barrier") {
          ports?.[0]?.postMessage({
            schema: 1,
            type: "marimo-studio:editor-document-mutation-ready",
            generation: message.generation,
          });
        }
      },
    ),
  };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  const unchanged = await server.notebookMutationPending(3, true);

  expect(unchanged).toEqual(expect.any(Function));
  expect(server.runtimeStatus().current.phase).toBe("synchronizing");
  expect(previewWindow.postMessage.mock.calls.map(([message]) => message.type)).toContain(
    "marimo-studio:presentation-refresh-barrier",
  );
  server.notebookMutationTransactionFailed(true);
  expect(server.runtimeStatus()).toMatchObject({
    current: {
      phase: "failed",
      diagnostics: [
        {
          code: "notebook-sync-failed",
          message: "Notebook change could not be synchronized.",
          hint: "Retry the edit to update this view.",
        },
      ],
    },
  });
  expect(unchanged()).toBe(true);
  expect(server.runtimeStatus().current.phase).toBe("ready");
  expect(unchanged()).toBe(false);
  server.dispose();
});

it("pauses a connecting presentation before admitting a notebook mutation", async () => {
  const preview = frame("complete");
  let barrierPort: MessagePort | undefined;
  const previewWindow = {
    postMessage: vi.fn((message: { type?: string }, _target: string, ports?: MessagePort[]) => {
      if (message.type === "marimo-studio:presentation-refresh-barrier") {
        barrierPort = ports?.[0];
      }
    }),
  };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );

  const pending = server.notebookMutationPending(4, true);

  expect(barrierPort).toBeUndefined();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  expect(barrierPort).toBeDefined();
  barrierPort!.postMessage({
    schema: 1,
    type: "marimo-studio:editor-document-mutation-ready",
    generation: 4,
  });
  await pending;
  server.dispose();
});

it("bounds a notebook mutation while a loading presentation has no receiver", async () => {
  vi.useFakeTimers();
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );

  const rejected = expect(server.notebookMutationPending(5, true)).rejects.toMatchObject({
    name: "TimeoutError",
  });
  await vi.advanceTimersByTimeAsync(4_000);
  await rejected;
  expect(previewWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-refresh-barrier" }),
    "*",
    expect.anything(),
  );
  server.dispose();
});

it("rejects a receiver for another view before admitting a notebook mutation", async () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "report",
    revision: "revision-other",
  });

  await expect(server.notebookMutationPending(6, true)).rejects.toMatchObject({
    name: "InvalidStateError",
  });
  expect(previewWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-refresh-barrier" }),
    "*",
    expect.anything(),
  );
  server.dispose();
});

it("rejects a notebook mutation from a retained blank presentation", async () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );
  preview.src = "about:blank";
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  await expect(server.notebookMutationPending(7, true)).rejects.toMatchObject({
    name: "InvalidStateError",
  });
  expect(previewWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-refresh-barrier" }),
    "*",
    expect.anything(),
  );
  server.dispose();
});

it("rejects a posted mutation barrier when its receiver disconnects", async () => {
  const preview = frame("complete");
  let barrierPosted = false;
  const previewWindow = {
    postMessage: vi.fn((message: { type?: string }) => {
      barrierPosted ||= message.type === "marimo-studio:presentation-refresh-barrier";
    }),
  };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  const rejected = expect(server.notebookMutationPending(8, true)).rejects.toMatchObject({
    name: "AbortError",
  });
  expect(barrierPosted).toBe(true);
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
  });
  await rejected;
  server.dispose();
});

it.each([
  ["deactivation", (server: PreviewController) => server.deactivate()],
  ["document reload", (server: PreviewController) => server.reload()],
  ["disposal", (server: PreviewController) => server.dispose()],
] as const)("cancels a receiver wait on presentation %s", async (_name, cancel) => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = controller(
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
  );
  const rejected = expect(server.notebookMutationPending(9, true)).rejects.toMatchObject({
    name: "AbortError",
  });

  cancel(server);
  await rejected;
  server.dispose();
});
