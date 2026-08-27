import { afterEach, expect, it, vi } from "vite-plus/test";

import { PreviewController } from "../src/features/preview/controller.ts";
import { PreviewDeck } from "../src/features/preview/deck.ts";
import { createFrameBridgeSource, installFrameBridge } from "./frame-bridge-test-support.ts";
import {
  acknowledgementPort,
  cachedFrames,
  dispatchPreviewMessage,
  dispatchPreviewRefreshHandshake,
  frame,
} from "./preview-test-support.ts";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

it("preserves a ready active frame when the editor reloads without a mutation", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
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
  deck.attach(editor, new Map([["server", preview]]));
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
  });
  const source = preview.src;
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);

  expect(deck.editorDocumentReloaded()).toBe(false);

  expect(preview.src).toBe(source);
  expect(deck.getSnapshot().states.server!.lifecycleId).toBe(lifecycleId);
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);
  deck.dispose();
});

it("clears stale interactivity only after an accepted unchanged completion", async () => {
  const preview = frame("complete");
  const previewWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
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
  });
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockResolvedValueOnce(() => false)
    .mockResolvedValueOnce(() => true);

  const rejected = acknowledgementPort();
  deck.notebookMutationPending(1, rejected.port);
  await vi.waitFor(() => expect(rejected.postMessage).toHaveBeenCalledOnce());
  expect(deck.editorDocumentReloaded()).toBe(true);
  const reloadedLifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  expect(reloadedLifecycleId).toBeGreaterThan(lifecycleId);
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: reloadedLifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: reloadedLifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });
  deck.notebookMutationTransactionApplied(1, false);
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);

  const accepted = acknowledgementPort();
  deck.notebookMutationPending(2, accepted.port);
  await vi.waitFor(() => expect(accepted.postMessage).toHaveBeenCalledOnce());
  deck.notebookMutationTransactionApplied(2, false);
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);

  gate.mockRestore();
  rejected.channel.port2.close();
  accepted.channel.port2.close();
  deck.dispose();
});

it("keeps a failed reloaded build inert until a repaired publication settles", async () => {
  const preview = frame("complete");
  const previewWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
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
  const initialLifecycle = deck.getSnapshot().states.server!.lifecycleId;
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: initialLifecycle,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: initialLifecycle,
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_initial",
  });
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockResolvedValue(() => true);
  const acknowledgement = acknowledgementPort();
  deck.notebookMutationPending(1, acknowledgement.port);
  await vi.waitFor(() => expect(acknowledgement.postMessage).toHaveBeenCalledOnce());

  expect(deck.editorDocumentReloaded()).toBe(true);
  const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  const source = preview.src;
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
    sessionId: "s_repair",
  });
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);

  deck.presentationBuildStarted("dashboard");
  deck.presentationBuildCompleted("dashboard", "revision-stale", 1);
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);

  deck.presentationBuildStarted("dashboard");
  deck.presentationBuildCompleted("dashboard", null);
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(false);

  deck.presentationBuildStarted("dashboard");
  deck.presentationBuildCompleted("dashboard", "revision-2");
  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-2",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-2",
    sessionId: "s_repair",
  });

  expect(preview.src).toBe(source);
  expect(deck.getSnapshot().states.server!.lifecycleId).toBe(lifecycleId);
  expect(preview.dataset.sessionId).toBe("s_repair");
  expect(deck.getSnapshot().frames.find(({ active }) => active)?.interactive).toBe(true);
  gate.mockRestore();
  acknowledgement.channel.port2.close();
  deck.dispose();
});

it("recreates a cached view after a pending mutation reloads the editor document", async () => {
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
  const frames = cachedFrames(deck, {});
  const windows = new Map(
    [...frames].map(([id, cached]) => {
      const frameWindow = createFrameBridgeSource();
      Object.defineProperty(cached, "contentWindow", { configurable: true, value: frameWindow });
      return [id, frameWindow];
    }),
  );
  deck.attach(frame("complete"), frames);

  const markReady = async (view: string, revision: string) => {
    const staged = deck.stageView(view);
    const selected = deck
      .getSnapshot()
      .frames.find((item) => item.runtime === "server" && item.view === view)!;
    const frameWindow = windows.get(selected.id)!;
    const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
    installFrameBridge(frames.get(selected.id)!, frameWindow, {
      lifecycleId,
      revision,
      runtime: "server",
      sessionId: "s_123456",
      view,
    });
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision,
    });
    dispatchPreviewMessage(frameWindow, {
      type: "marimo-studio:view-ready",
      runtime: "server",
      view,
      lifecycleId,
      revision,
    });
    await expect(staged.ready).resolves.toBe(true);
    return { frame: frames.get(selected.id)!, frameWindow, lifecycleId };
  };

  const initialDashboard = deck
    .getSnapshot()
    .frames.find((item) => item.runtime === "server" && item.view === "dashboard")!;
  const initialDashboardWindow = windows.get(initialDashboard.id)!;
  const initialDashboardLifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  installFrameBridge(frames.get(initialDashboard.id)!, initialDashboardWindow, {
    lifecycleId: initialDashboardLifecycleId,
    revision: "revision:dashboard:old",
    runtime: "server",
    sessionId: "s_123456",
    view: "dashboard",
  });
  dispatchPreviewMessage(initialDashboardWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId: initialDashboardLifecycleId,
    revision: "revision:dashboard:old",
  });
  dispatchPreviewMessage(initialDashboardWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId: initialDashboardLifecycleId,
    revision: "revision:dashboard:old",
  });
  await vi.waitFor(() => expect(deck.runtimeDiagnostics("server")?.current.phase).toBe("ready"));
  const dashboard = {
    frame: frames.get(initialDashboard.id)!,
    frameWindow: initialDashboardWindow,
    lifecycleId: initialDashboardLifecycleId,
  };
  deck.presentationBaseline("dashboard", "revision:dashboard:old");
  await markReady("qa-view", "revision:qa");
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockResolvedValue(() => true);
  const acknowledgement = acknowledgementPort();
  deck.notebookMutationPending(1, acknowledgement.port);
  await vi.waitFor(() => expect(acknowledgement.postMessage).toHaveBeenCalledOnce());

  expect(deck.editorDocumentReloaded()).toBe(true);
  expect(dashboard.frame.src).toBe("about:blank");
  dashboard.frameWindow.postMessage.mockClear();

  const recreated = deck.stageView("dashboard");
  const selected = deck
    .getSnapshot()
    .frames.find((item) => item.runtime === "server" && item.view === "dashboard")!;
  const frameWindow = windows.get(selected.id)!;
  const lifecycleId = deck.getSnapshot().states.server!.lifecycleId;
  installFrameBridge(frames.get(selected.id)!, frameWindow, {
    lifecycleId,
    revision: "revision:dashboard:new",
    runtime: "server",
    sessionId: "s_123456",
    view: "dashboard",
  });
  expect(lifecycleId).toBeGreaterThan(dashboard.lifecycleId);
  expect(frameWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-change" }),
    "*",
  );
  expect(frameWindow.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-refresh" }),
    "*",
  );
  dispatchPreviewMessage(frameWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId,
    revision: "revision:dashboard:new",
  });
  dispatchPreviewMessage(frameWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    lifecycleId,
    revision: "revision:dashboard:new",
  });

  await expect(recreated.ready).resolves.toBe(true);
  expect(deck.runtimeDiagnostics("server")).toMatchObject({
    revision: "revision:dashboard:new",
    current: { phase: "ready" },
  });
  gate.mockRestore();
  acknowledgement.channel.port2.close();
  deck.dispose();
});
