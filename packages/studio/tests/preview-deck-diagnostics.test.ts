import { afterEach, expect, it, vi } from "vite-plus/test";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";
import { PreviewController } from "../src/features/preview/controller.ts";
import { installFrameBridge } from "./frame-bridge-test-support.ts";
import { controller, dispatchPreviewMessage, frame, previewDeck } from "./preview-test-support.ts";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

const projectionDiagnostic = {
  code: "projection-missing",
  severity: "error" as const,
  message: "The projected value is missing.",
  hint: "Restore the value in the notebook.",
  view: "dashboard",
  scope: "projection",
  projection: "value" as const,
  target: "user_note",
};

const interactiveHarness = () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const server = new PreviewController(
    "dashboard",
    "server",
    frame("complete"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  return { preview, previewWindow, server };
};

it("keeps an exact projection failure interactive while a runtime failure blocks the frame", () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const deck = previewDeck();
  deck.attach(frame("complete"), new Map([["server", preview]]));
  const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });
  const stopControls = vi.spyOn(PreviewControlController.prototype, "stop");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-1",
    diagnostic: projectionDiagnostic,
  });

  expect(deck.runtimeDiagnostics("server")?.current).toMatchObject({
    phase: "failed",
    diagnostics: [projectionDiagnostic],
  });
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);
  expect(stopControls).not.toHaveBeenCalled();

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-1",
    diagnostic: { ...projectionDiagnostic, code: "runtime-failed", scope: "runtime" },
  });

  expect(deck.runtimeDiagnostics("server")?.current.phase).toBe("failed");
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);
  expect(stopControls).toHaveBeenCalledOnce();

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-1",
    diagnostic: projectionDiagnostic,
  });
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);
  stopControls.mockRestore();
  deck.dispose();
});

it("admits a session-bearing projection error after its delayed build completes", () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const deck = previewDeck();
  deck.attach(frame("complete"), new Map([["server", preview]]));
  const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  deck.presentationBuildStarted("dashboard");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-2",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-2",
    sessionId: "s_error2",
    diagnostic: projectionDiagnostic,
  });

  expect(preview.dataset.sessionId).toBe("s_error2");
  expect(deck.runtimeDiagnostics("server")).toMatchObject({
    revision: "revision-2",
    sessionId: "s_error2",
    current: { phase: "failed", diagnostics: [projectionDiagnostic] },
  });
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);
  const beginControls = vi
    .spyOn(PreviewControlController.prototype, "begin")
    .mockImplementation(() => undefined);

  deck.presentationBuildCompleted("dashboard", "revision-2");

  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);
  expect(beginControls).toHaveBeenCalledOnce();
  expect(beginControls).toHaveBeenCalledWith("revision-2", "s_error2", undefined);
  expect(deck.runtimeDiagnostics("server")?.current.phase).toBe("failed");
  beginControls.mockRestore();
  deck.dispose();
});

it("defers an inactive localized commit until activation owns its controls", async () => {
  const { preview, previewWindow, server } = interactiveHarness();
  server.presentationBuildStarted();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-2",
  });
  server.deactivate();
  const beginControls = vi
    .spyOn(PreviewControlController.prototype, "begin")
    .mockImplementation(() => undefined);
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-2",
    sessionId: "s_error2",
    diagnostic: projectionDiagnostic,
  });
  server.presentationBuildCompleted("revision-2");

  expect(beginControls).not.toHaveBeenCalled();
  installFrameBridge(preview, previewWindow, {
    lifecycleId: 1,
    revision: "revision-2",
    runtime: "server",
    sessionId: "s_error2",
    view: "dashboard",
  });

  await expect(server.activate({ query: "", hash: "" })).resolves.toBe(true);

  expect(beginControls).toHaveBeenCalledOnce();
  expect(beginControls).toHaveBeenCalledWith("revision-2", "s_error2", undefined);
  expect(preview.dataset.sessionId).toBe("s_error2");
  expect(server.runtimeStatus().current.phase).toBe("failed");
  beginControls.mockRestore();
  server.dispose();
});

it("reactivates a warm projection failure and restarts its controls", async () => {
  const { preview, previewWindow, server } = interactiveHarness();
  server.presentationBaseline("revision-1");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
    diagnostic: projectionDiagnostic,
  });
  expect(server.readyForInteraction()).toBe(true);
  expect(server.runtimeStatus().current.phase).toBe("failed");
  const source = preview.src;
  const lifecycleId = preview.dataset.previewLifecycleId;
  server.deactivate();
  installFrameBridge(preview, previewWindow, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "server",
    sessionId: null,
    view: "dashboard",
  });
  const beginControls = vi.spyOn(PreviewControlController.prototype, "begin");
  previewWindow.postMessage.mockClear();

  await expect(server.activate({ query: "", hash: "" })).resolves.toBe(true);

  expect(preview.src).toBe(source);
  expect(preview.dataset.previewLifecycleId).toBe(lifecycleId);
  expect(server.readyForInteraction()).toBe(true);
  expect(server.runtimeStatus().current.phase).toBe("failed");
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:frame-query-apply" }),
    "*",
  );
  expect(beginControls).toHaveBeenCalledWith("revision-1", undefined, undefined);
  beginControls.mockRestore();
  server.dispose();
});

it("refreshes a warm fatal failure before reactivation completes", async () => {
  const { preview, previewWindow, server } = interactiveHarness();
  server.presentationBaseline("revision-1");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
    diagnostic: { ...projectionDiagnostic, code: "runtime-failed", scope: "runtime" },
  });
  expect(server.readyForInteraction()).toBe(false);
  const source = preview.src;
  const lifecycleId = preview.dataset.previewLifecycleId;
  server.deactivate();
  installFrameBridge(preview, previewWindow, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "server",
    sessionId: null,
    view: "dashboard",
  });
  previewWindow.postMessage.mockClear();

  const activating = server.activate({ query: "", hash: "" });
  let settled = false;
  void activating.then(() => {
    settled = true;
  });
  await Promise.resolve();

  expect(settled).toBe(false);
  expect(preview.src).toBe(source);
  expect(preview.dataset.previewLifecycleId).toBe(lifecycleId);
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-change" }),
    "*",
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  await expect(activating).resolves.toBe(true);
  expect(server.readyForInteraction()).toBe(true);
  server.dispose();
});

it("retains a cleared preview diagnostic in runtime history", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
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
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-diagnostics",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    diagnostics: [
      {
        code: "value-stale",
        severity: "warning",
        message: "The projected value is stale.",
        hint: "Wait for the notebook to finish running.",
        view: "dashboard",
        scope: "projection",
        projection: "value",
        target: "summary.total",
      },
    ],
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-diagnostics",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    diagnostics: [],
  });

  const report = server.runtimeStatus();
  expect(report.current.phase).toBe("ready");
  expect(report.transitions.map(({ phase }) => phase)).toEqual([
    "connecting",
    "ready",
    "degraded",
    "ready",
  ]);
  expect(report.transitions[2]?.diagnostics[0]?.code).toBe("value-stale");
  server.dispose();
});
