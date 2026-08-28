import { afterEach, expect, it, vi } from "vite-plus/test";

import { PreviewController } from "../src/features/preview/controller.ts";
import {
  PREVIEW_VIEW_CACHE_SIZE,
  PreviewDeck,
  WASM_PREVIEW_VIEW_CACHE_SIZE,
} from "../src/features/preview/deck.ts";
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

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

it("restores the prior controller and editor query after a target view fails", async () => {
  let editorQuery = "?region=emea";
  let queryOwner: WeakRef<PreviewController> | undefined;
  const originalSynchronize = PreviewController.prototype.synchronizeNavigationQuery;
  vi.spyOn(PreviewController.prototype, "synchronizeNavigationQuery").mockImplementation(function (
    this: PreviewController,
    query: string,
  ) {
    queryOwner = new WeakRef(this);
    return originalSynchronize.call(this, query);
  });
  const originalRollback = PreviewController.prototype.rollbackNavigation;
  vi.spyOn(PreviewController.prototype, "rollbackNavigation").mockImplementation(function (
    this: PreviewController,
    query?: string,
  ) {
    queryOwner = new WeakRef(this);
    return originalRollback.call(this, query);
  });
  const syncEditorQuery = vi.fn(async (query: string, operationId: string) => {
    const owner = queryOwner?.deref();
    if (!owner) {
      throw new Error("Query synchronization did not capture a controller owner.");
    }
    queueMicrotask(() => {
      editorQuery = query;
      owner.editorQueryChanged(query, operationId, true);
    });
    return "accepted" as const;
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "wasm",
    initialNavigation: { query: "?region=emea", hash: "#overview" },
    runtimes: ["wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery,
    navigate: vi.fn(),
  });
  const editor = frame("loading");
  const frames = cachedFrames(deck, {});
  const windows = new Map(
    [...frames].map(([id, preview]) => {
      const source = createFrameBridgeSource();
      Object.defineProperty(preview, "contentWindow", { configurable: true, value: source });
      return [id, source];
    }),
  );
  deck.attach(editor, frames);
  const dashboard = deck
    .getSnapshot()
    .frames.find(({ runtime, view }) => runtime === "wasm" && view === "dashboard")!;
  const dashboardWindow = windows.get(dashboard.id)!;
  const dashboardLifecycleId = deck.getSnapshot().states.wasm!.lifecycleId;
  installFrameBridge(frames.get(dashboard.id)!, dashboardWindow, {
    lifecycleId: dashboardLifecycleId,
    revision: "revision:dashboard",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "wasm",
    lifecycleId: dashboardLifecycleId,
    view: "dashboard",
    revision: "revision:dashboard",
  });
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: dashboardLifecycleId,
    view: "dashboard",
    revision: "revision:dashboard",
  });

  const owner = new AbortController();
  const staged = deck.stageNavigation(
    "report",
    true,
    { query: "?region=apac", hash: "#details" },
    owner.signal,
  );
  await vi.waitFor(() => expect(syncEditorQuery).toHaveBeenCalledOnce());
  await vi.waitFor(() =>
    expect(deck.getSnapshot().frames.some(({ active, view }) => active && view === "report")).toBe(
      true,
    ),
  );
  owner.abort();
  await expect(staged.ready).resolves.toBe(false);
  expect(editorQuery).toBe("?region=apac");
  const rollingBack = staged.rollback();
  await vi.waitFor(() =>
    expect(
      deck.getSnapshot().frames.some(({ active, view }) => active && view === "dashboard"),
    ).toBe(true),
  );
  const restoredLifecycleId = deck.getSnapshot().states.wasm!.lifecycleId;
  installFrameBridge(frames.get(dashboard.id)!, dashboardWindow, {
    lifecycleId: restoredLifecycleId,
    revision: "revision:dashboard",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "wasm",
    lifecycleId: restoredLifecycleId,
    view: "dashboard",
    revision: "revision:dashboard",
  });
  dispatchPreviewMessage(dashboardWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: restoredLifecycleId,
    view: "dashboard",
    revision: "revision:dashboard",
  });
  await expect(rollingBack).resolves.toBeUndefined();
  await expect(staged.rollback()).resolves.toBeUndefined();

  expect(editorQuery).toBe("?region=emea");
  expect(syncEditorQuery.mock.calls.map(([query]) => query)).toEqual([
    "?region=apac",
    "?region=emea",
  ]);
  expect(deck.getSnapshot().frames.some(({ active, view }) => active && view === "dashboard")).toBe(
    true,
  );
  deck.dispose();
});

it("keeps the runtime stable until a staged navigation commits", async () => {
  const ready = deferred<boolean>();
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  vi.spyOn(deck, "stageView").mockReturnValue({
    ready: ready.promise,
    rollback: async () => {},
  });

  const staged = deck.stageNavigation("report", true);
  deck.switchRuntime("wasm");
  expect(deck.getSnapshot().runtime).toBe("server");

  ready.resolve(true);
  await expect(staged.ready).resolves.toBe(true);
  staged.commit?.();
  deck.switchRuntime("wasm");
  expect(deck.getSnapshot().runtime).toBe("wasm");
  deck.dispose();
});

it("starts an inactive runtime when the user selects it", () => {
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  wasmFrame.src = "about:blank";
  const serverWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  const inactiveSource = wasmFrame.src;
  expect(deck.frameIds.filter((id) => id.startsWith("server"))).toHaveLength(
    PREVIEW_VIEW_CACHE_SIZE,
  );
  expect(deck.frameIds.filter((id) => id.startsWith("wasm"))).toHaveLength(
    WASM_PREVIEW_VIEW_CACHE_SIZE,
  );
  dispatchPreviewMessage(serverWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: deck.getSnapshot().states.server!.lifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });

  expect(wasmFrame.src).toBe(inactiveSource);
  deck.switchRuntime("wasm");
  expect(wasmFrame.src).toContain("runtime=wasm");
  deck.dispose();
});

it("refreshes the selected preview without reconnecting an inactive runtime", async () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  const wasmWindow = createFrameBridgeSource();
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  Object.defineProperty(wasmFrame, "contentWindow", {
    configurable: true,
    value: wasmWindow,
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  deck.switchRuntime("wasm");
  installFrameBridge(wasmFrame, wasmWindow, {
    lifecycleId: deck.getSnapshot().states.wasm!.lifecycleId,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  for (const [runtime, source] of [
    ["server", serverWindow],
    ["wasm", wasmWindow],
  ] as const) {
    dispatchPreviewMessage(source, {
      type: "marimo-studio:view-ready",
      runtime,
      lifecycleId: deck.getSnapshot().states[runtime]!.lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    await vi.waitFor(() => expect(deck.runtimeDiagnostics(runtime)?.current.phase).toBe("ready"));
  }
  const inactiveSource = serverFrame.src;
  const inactiveState = deck.runtimeDiagnostics("server");
  const selectedLifecycle = deck.getSnapshot().states.wasm!.lifecycleId;

  deck.reload();

  expect(serverFrame.src).toBe(inactiveSource);
  expect(deck.runtimeDiagnostics("server")).toEqual(inactiveState);
  expect(wasmFrame.src).toContain("runtime=wasm");
  expect(deck.getSnapshot().states.wasm!.lifecycleId).toBeGreaterThan(selectedLifecycle);
  expect(deck.runtimeDiagnostics("wasm")).toMatchObject({
    revision: null,
    current: { phase: "connecting", diagnostics: [] },
  });
  deck.dispose();
});

it("refreshes a changed presentation when an inactive runtime becomes active", async () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = createFrameBridgeSource();
  const wasmWindow = createFrameBridgeSource();
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  Object.defineProperty(wasmFrame, "contentWindow", {
    configurable: true,
    value: wasmWindow,
  });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  const markReady = async (
    runtime: "server" | "wasm",
    preview: HTMLIFrameElement,
    previewWindow: ReturnType<typeof createFrameBridgeSource>,
  ) => {
    const lifecycleId = deck.getSnapshot().states[runtime]!.lifecycleId;
    installFrameBridge(preview, previewWindow, {
      lifecycleId,
      revision: "revision-1",
      runtime,
      sessionId: null,
      view: "dashboard",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:receiver-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    await vi.waitFor(() => expect(deck.runtimeDiagnostics(runtime)?.current.phase).toBe("ready"));
  };

  await markReady("server", serverFrame, serverWindow);
  deck.switchRuntime("wasm");
  await markReady("wasm", wasmFrame, wasmWindow);
  const serverRefreshOffset = serverWindow.postMessage.mock.calls.length;
  deck.switchRuntime("server");
  expect(
    deck.getSnapshot().frames.find(({ active, runtime }) => active && runtime === "server")
      ?.interactive,
  ).toBe(false);
  expect(
    serverWindow.postMessage.mock.calls
      .slice(serverRefreshOffset)
      .some(([message]) => message.type === "marimo-studio:presentation-change"),
  ).toBe(true);
  dispatchPreviewRefreshHandshake(serverWindow, {
    runtime: "server",
    lifecycleId: deck.getSnapshot().states.server!.lifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(serverWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: deck.getSnapshot().states.server!.lifecycleId,
    view: "dashboard",
    revision: "revision-1",
  });
  expect(
    deck.getSnapshot().frames.find(({ active, runtime }) => active && runtime === "server")
      ?.interactive,
  ).toBe(true);
  await vi.waitFor(() =>
    expect(
      serverWindow.postMessage.mock.calls.some(
        ([message]) => message.type === "marimo-studio:frame-query-apply",
      ),
    ).toBe(true),
  );
  serverWindow.postMessage.mockClear();
  wasmWindow.postMessage.mockClear();
  const wasmSource = wasmFrame.src;
  const wasmLifecycleId = deck.getSnapshot().states.wasm!.lifecycleId;

  deck.presentationBuildStarted("dashboard");
  serverWindow.postMessage.mockClear();
  wasmWindow.postMessage.mockClear();
  deck.presentationBuildCompleted("dashboard", "revision-2");
  deck.presentationChanged("dashboard", "revision-2");

  expect(serverWindow.postMessage.mock.calls).toEqual([
    [
      {
        type: "marimo-studio:presentation-refresh",
        runtime: "server",
        lifecycleId: deck.getSnapshot().states.server!.lifecycleId,
        view: "dashboard",
        phase: "settled",
      },
      "*",
    ],
    [
      {
        type: "marimo-studio:presentation-change",
        runtime: "server",
        lifecycleId: deck.getSnapshot().states.server!.lifecycleId,
        view: "dashboard",
      },
      "*",
    ],
  ]);
  expect(
    wasmWindow.postMessage.mock.calls.some(
      ([message]) => message.type === "marimo-studio:presentation-change",
    ),
  ).toBe(false);

  deck.switchRuntime("wasm");

  await vi.waitFor(() =>
    expect(wasmWindow.postMessage).toHaveBeenCalledWith(
      {
        type: "marimo-studio:presentation-change",
        runtime: "wasm",
        lifecycleId: wasmLifecycleId,
        view: "dashboard",
      },
      "*",
    ),
  );
  expect(wasmFrame.src).toBe(wasmSource);
  expect(deck.getSnapshot().states.wasm!.lifecycleId).toBe(wasmLifecycleId);
  expect(deck.runtimeDiagnostics("wasm")?.current.phase).toBe("synchronizing");
  expect(
    deck.getSnapshot().frames.find(({ active, runtime }) => active && runtime === "wasm")
      ?.interactive,
  ).toBe(false);
  deck.dispose();
});

it("retains an exact server frame after a delayed same-revision baseline", async () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = createFrameBridgeSource();
  const wasmWindow = createFrameBridgeSource();
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "", hash: "" },
    runtimes: ["server", "wasm"],
    viewUrl: (view, runtime) => `/${view}?runtime=${runtime}`,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  const markReady = async (
    runtime: "server" | "wasm",
    preview: HTMLIFrameElement,
    previewWindow: ReturnType<typeof createFrameBridgeSource>,
    sessionId: string,
  ) => {
    const lifecycleId = deck.getSnapshot().states[runtime]!.lifecycleId;
    installFrameBridge(preview, previewWindow, {
      lifecycleId,
      revision: "revision-1",
      runtime,
      sessionId,
      view: "dashboard",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:receiver-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
      sessionId,
    });
    await vi.waitFor(() => expect(deck.runtimeDiagnostics(runtime)?.current.phase).toBe("ready"));
  };

  await markReady("server", serverFrame, serverWindow, "s_server1");
  const serverSource = serverFrame.src;
  const serverLifecycle = deck.getSnapshot().states.server!.lifecycleId;
  expect(deck.getSnapshot().frames.find(({ runtime }) => runtime === "server")?.interactive).toBe(
    true,
  );

  deck.switchRuntime("wasm");
  await markReady("wasm", wasmFrame, wasmWindow, "s_wasm01");
  deck.presentationBaseline("dashboard", "revision-1");
  serverWindow.postMessage.mockClear();

  deck.switchRuntime("server");

  expect(serverFrame.src).toBe(serverSource);
  expect(deck.getSnapshot().states.server!.lifecycleId).toBe(serverLifecycle);
  expect(serverFrame.dataset.sessionId).toBe("s_server1");
  expect(
    deck.getSnapshot().frames.find(({ active, runtime }) => active && runtime === "server")
      ?.interactive,
  ).toBe(true);
  expect(
    serverWindow.postMessage.mock.calls.some(
      ([message]) => message.type === "marimo-studio:presentation-change",
    ),
  ).toBe(false);
  deck.dispose();
});

it("seeds initial deep-link query and hash into every runtime state", () => {
  const viewUrl = vi.fn(
    (view: string, runtime: string, navigation?: { query: string; hash: string }) =>
      `/${view}/?runtime=${runtime}&${navigation?.query.slice(1) ?? ""}${navigation?.hash ?? ""}`,
  );
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "?region=emea", hash: "#details" },
    runtimes: ["server", "wasm"],
    viewUrl,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });

  expect(deck.getSnapshot().states.server?.url).toContain("region=emea#details");
  expect(deck.getSnapshot().states.wasm?.url).toContain("region=emea#details");
  expect(viewUrl).toHaveBeenCalledWith("dashboard", "server", {
    query: "?region=emea",
    hash: "#details",
  });
  expect(viewUrl).toHaveBeenCalledWith("dashboard", "wasm", {
    query: "?region=emea",
    hash: "#details",
  });
  deck.dispose();
});

it("seeds the current navigation intent into a lazily created runtime", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const viewUrl = vi.fn(
    (view: string, runtime: string, navigation?: { query: string; hash: string }) =>
      `/${view}/?runtime=${runtime}&${navigation?.query.slice(1) ?? ""}${navigation?.hash ?? ""}`,
  );
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    initialNavigation: { query: "?region=emea", hash: "#overview" },
    runtimes: ["server", "wasm"],
    viewUrl,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );

  deck.navigateWithinView({ query: "?region=apac", hash: "#detail" });
  deck.switchRuntime("wasm");

  expect(viewUrl).toHaveBeenLastCalledWith("dashboard", "wasm", {
    query: "?region=apac",
    hash: "#detail",
  });
  expect(deck.getSnapshot().states.wasm?.url).toContain("region=apac#detail");
  deck.dispose();
});

it("awaits only the active preview and reloads an inactive cached view", async () => {
  const activate = vi.spyOn(PreviewController.prototype, "activate").mockResolvedValue(true);
  const unchanged = vi.fn(() => true);
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockResolvedValue(unchanged);
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
  const frames = cachedFrames(deck, { server: frame("complete") });
  const dashboardFrame = frames.get("server")!;
  deck.attach(frame("complete"), frames);
  await expect(deck.stageView("report").ready).resolves.toBe(true);
  const reportFrameId = deck.getSnapshot().frames.find(({ active }) => active)!.id;
  const reportFrame = frames.get(reportFrameId)!;
  activate.mockClear();
  const acknowledgement = acknowledgementPort();

  deck.notebookMutationPending(8, acknowledgement.port);
  await vi.waitFor(() => expect(acknowledgement.postMessage).toHaveBeenCalledOnce());

  expect(gate).toHaveBeenCalledTimes(1);
  expect(gate).toHaveBeenCalledWith(8, true);
  expect(dashboardFrame.src).toBe("about:blank");
  await expect(deck.stageView("dashboard").ready).resolves.toBe(true);
  expect(dashboardFrame.src).toContain("/dashboard?runtime=server");
  expect(reportFrame.src).toBe("about:blank");
  expect(activate).toHaveBeenCalled();
  deck.dispose();
  acknowledgement.channel.port2.close();
  gate.mockRestore();
  activate.mockRestore();
});

it("disposes an unresponsive active reader before acknowledging the editor", async () => {
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockRejectedValue(new DOMException("preview unavailable", "TimeoutError"));
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
  const frameElement = frame("complete");
  deck.attach(frame("complete"), cachedFrames(deck, { server: frameElement }));
  const acknowledgement = acknowledgementPort();

  deck.notebookMutationPending(9, acknowledgement.port);
  await vi.waitFor(() => expect(acknowledgement.postMessage).toHaveBeenCalledOnce());

  expect(frameElement.src).toBe("about:blank");
  expect(deck.getSnapshot().states.server?.status.message).toBe("Updating preview");
  deck.notebookMutationTransactionFailed(9);
  expect(deck.getSnapshot().states.server?.status.message).toBe("Needs repair");
  deck.presentationBuildStarted("dashboard", 9);
  expect(frameElement.src).toContain("/dashboard?runtime=server");
  deck.dispose();
  acknowledgement.channel.port2.close();
  gate.mockRestore();
});

it("gates a replacement view before acknowledging a switched editor mutation", async () => {
  let rejectOld!: (cause: unknown) => void;
  const oldGate = new Promise<() => boolean>((_resolve, reject) => {
    rejectOld = reject;
  });
  const replacementUnchanged = vi.fn(() => true);
  const gate = vi
    .spyOn(PreviewController.prototype, "notebookMutationPending")
    .mockReturnValueOnce(oldGate)
    .mockResolvedValue(replacementUnchanged);
  const dispose = vi.spyOn(PreviewController.prototype, "dispose");
  const activate = vi.spyOn(PreviewController.prototype, "activate").mockResolvedValue(true);
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
  const dashboard = frame("complete");
  deck.attach(frame("complete"), cachedFrames(deck, { server: dashboard }));
  const acknowledgement = acknowledgementPort();
  deck.notebookMutationPending(10, acknowledgement.port);
  await vi.waitFor(() => expect(gate).toHaveBeenCalledOnce());

  await expect(deck.stageView("report").ready).resolves.toBe(true);
  rejectOld(new DOMException("old view disposed", "AbortError"));
  await vi.waitFor(() => expect(acknowledgement.postMessage).toHaveBeenCalledOnce());

  expect(gate).toHaveBeenCalledTimes(2);
  expect(dispose).toHaveBeenCalled();
  deck.notebookMutationTransactionApplied(10, false);
  expect(replacementUnchanged).toHaveBeenCalledOnce();
  deck.dispose();
  acknowledgement.channel.port2.close();
  gate.mockRestore();
  activate.mockRestore();
  dispose.mockRestore();
});
