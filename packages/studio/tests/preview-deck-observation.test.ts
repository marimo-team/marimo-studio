import { afterEach, expect, it, vi } from "vite-plus/test";

import type { RecordBrowserObservation } from "../src/features/preview/observation-remote.ts";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";
import { PreviewController } from "../src/features/preview/controller.ts";
import { PreviewDeck } from "../src/features/preview/deck.ts";
import { PreviewObservationController } from "../src/features/preview/observation-controller.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";
import { installFrameBridge } from "./frame-bridge-test-support.ts";
import {
  controller,
  dispatchPreviewMessage,
  dispatchPreviewRefreshHandshake,
  frame,
} from "./preview-test-support.ts";

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

const observationHarness = () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const record = vi.fn<RecordBrowserObservation>(async () => undefined);
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
    record,
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
  return { preview, previewWindow, record, server };
};

it.each(["ready", "error"] as const)(
  "accepts a same-request loading observation followed by terminal %s evidence",
  async (terminal) => {
    const { previewWindow, record, server } = observationHarness();
    const stopControls = vi.spyOn(PreviewControlController.prototype, "stop");
    const request = {
      schema: 1 as const,
      requestId: `request-${terminal}`,
      view: "dashboard",
      runtime: "server",
      runtimeInstance: "runtime-instance",
      revision: "revision-1",
    };
    server.requestObservation(request);
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-observation",
      lifecycleId: 1,
      requestId: request.requestId,
      view: request.view,
      runtime: request.runtime,
      runtimeInstance: request.runtimeInstance,
      revision: request.revision,
      state: "loading",
      diagnostics: [],
      sessionId: "s_123456",
      query: "",
      ...emptyProjectionEvidence,
    });
    expect(server.runtimeStatus().current.phase).toBe("synchronizing");

    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-observation",
      lifecycleId: 1,
      requestId: request.requestId,
      view: request.view,
      runtime: request.runtime,
      runtimeInstance: request.runtimeInstance,
      revision: request.revision,
      state: terminal,
      diagnostics: terminal === "error" ? [projectionDiagnostic] : [],
      sessionId: "s_123456",
      query: "",
      ...emptyProjectionEvidence,
    });

    await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(2));
    expect(server.runtimeStatus().current.phase).toBe(terminal === "ready" ? "ready" : "failed");
    expect(server.readyForInteraction()).toBe(true);
    expect(stopControls).not.toHaveBeenCalled();
    server.dispose();
    stopControls.mockRestore();
  },
);

it("keeps an exact projection failure interactive while a runtime failure blocks the frame", () => {
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
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
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
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
  const { preview, previewWindow, server } = observationHarness();
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
  const postObservations = vi.spyOn(PreviewObservationController.prototype, "post");
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
  expect(postObservations).not.toHaveBeenCalled();
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
  expect(postObservations).toHaveBeenCalledOnce();
  expect(preview.dataset.sessionId).toBe("s_error2");
  expect(server.runtimeStatus().current.phase).toBe("failed");
  postObservations.mockRestore();
  beginControls.mockRestore();
  server.dispose();
});

it("reactivates a warm projection failure and restarts its controls", async () => {
  const { preview, previewWindow, server } = observationHarness();
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
  server.requestObservation({
    schema: 1,
    requestId: "localized-retry",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-instance",
    revision: "revision-1",
  });
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:observe-view",
      requestId: "localized-retry",
    }),
    "*",
  );
  beginControls.mockRestore();
  server.dispose();
});

it("refreshes a warm fatal failure before reactivation completes", async () => {
  const { preview, previewWindow, server } = observationHarness();
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

it("ignores observation requests while its cached controller is inactive", () => {
  const { previewWindow, server } = observationHarness();
  server.deactivate();
  previewWindow.postMessage.mockClear();

  server.requestObservation({
    schema: 1,
    requestId: "inactive-observation",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-instance",
    revision: "revision-1",
  });

  expect(previewWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:observe-view" }),
    "*",
  );
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

it("ignores superseded observation replies before updating runtime identity", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const report = vi.fn();
  const record = vi.fn<RecordBrowserObservation>(async () => undefined);
  const server = new PreviewController(
    "dashboard",
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    report,
    record,
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
  server.requestObservation({
    schema: 1,
    requestId: "stale-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "stale-instance",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-2",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-2",
  });
  server.requestObservation({
    schema: 1,
    requestId: "current-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "current-instance",
    revision: "revision-2",
  });
  report.mockClear();

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    lifecycleId: 1,
    requestId: "stale-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "stale-instance",
    revision: "revision-1",
    state: "ready",
    diagnostics: [],
    sessionId: "s_stale1",
    query: "",
    ...emptyProjectionEvidence,
  });

  expect(report).not.toHaveBeenCalled();
  expect(preview.dataset.sessionId).toBeUndefined();
  expect(server.runtimeStatus()).toMatchObject({
    revision: "revision-2",
    sessionId: null,
    current: { phase: "ready" },
  });

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    lifecycleId: 1,
    requestId: "current-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "current-instance",
    revision: "revision-2",
    state: "ready",
    diagnostics: [],
    sessionId: "s_current2",
    query: "",
    ...emptyProjectionEvidence,
  });

  expect(preview.dataset.sessionId).toBe("s_current2");
  expect(server.runtimeStatus()).toMatchObject({
    revision: "revision-2",
    sessionId: "s_current2",
    current: { phase: "ready" },
  });
  expect(record).toHaveBeenCalledTimes(1);
  expect(record).toHaveBeenCalledWith(expect.objectContaining({ requestId: "current-request" }));
  server.dispose();
});

it("rejects an old observation after a new presentation build starts", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const record = vi.fn<RecordBrowserObservation>(async () => undefined);
  const server = new PreviewController(
    "dashboard",
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
    record,
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-old",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-old",
  });
  server.requestObservation({
    schema: 1,
    requestId: "old-observation",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-old",
    revision: "revision-old",
  });

  server.presentationBuildStarted();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    lifecycleId: 1,
    requestId: "old-observation",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-old",
    revision: "revision-old",
    state: "ready",
    diagnostics: [],
    sessionId: "s_old123",
    query: "",
    ...emptyProjectionEvidence,
  });

  expect(server.runtimeStatus().current.phase).toBe("synchronizing");
  expect(record).not.toHaveBeenCalled();

  server.presentationBuildCompleted("revision-new");
  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-new",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-new",
  });
  server.requestObservation({
    schema: 1,
    requestId: "new-observation",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-new",
    revision: "revision-new",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    lifecycleId: 1,
    requestId: "new-observation",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-new",
    revision: "revision-new",
    state: "ready",
    diagnostics: [],
    sessionId: "s_new123",
    query: "",
    ...emptyProjectionEvidence,
  });

  expect(server.runtimeStatus()).toMatchObject({
    revision: "revision-new",
    current: { phase: "ready" },
  });
  expect(record).toHaveBeenCalledOnce();
  expect(record).toHaveBeenCalledWith(
    expect.objectContaining({ requestId: "new-observation", revision: "revision-new" }),
  );
  server.dispose();
});
