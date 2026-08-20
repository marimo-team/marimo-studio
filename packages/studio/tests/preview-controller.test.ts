import type { BrowserDiagnostic } from "@marimo-studio/protocol/browser-observations";

import { afterEach, expect, it, vi } from "vite-plus/test";

import type { ControlEndpoint, ControlUpdate } from "../src/features/preview/control-sync.ts";
import type { EditorQuerySyncResult } from "../src/features/preview/query-remote.ts";

import { PreviewController } from "../src/features/preview/controller.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";
import {
  createFrameBridgeSource,
  installFrameBridge,
  sendFrameControlUpdate,
} from "./frame-bridge-test-support.ts";
import {
  controlEndpoint,
  controller,
  dispatchPreviewMessage,
  dispatchPreviewRefreshHandshake,
  frame,
  runtimeConfig,
} from "./preview-test-support.ts";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.body.replaceChildren();
});

it("forwards authored navigation intent without mutating query state", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const syncQuery = vi.fn();
  const navigate = vi.fn(async () => false);
  const server = new PreviewController(
    "dashboard",
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    syncQuery,
    vi.fn(async () => "accepted" as const),
    navigate,
    vi.fn(),
  );

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:navigate-view",
    runtime: "server",
    lifecycleId: 1,
    view: "report",
    query: "?file=analysis.py&region=emea",
    hash: "#details",
  });

  expect(syncQuery).not.toHaveBeenCalled();
  expect(navigate).toHaveBeenCalledWith("report", {
    query: "?file=analysis.py&region=emea",
    hash: "#details",
  });
  server.dispose();
});

it("ignores wrapper-local replay hints", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = { postMessage: vi.fn() };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const syncQuery = vi.fn();
  const navigate = vi.fn();
  const report = vi.fn();
  const server = new PreviewController(
    "dashboard",
    "server",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    syncQuery,
    vi.fn(async () => "accepted" as const),
    navigate,
    report,
  );

  const replay = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:replay-document",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      url: "/_marimo-studio/presentation/d.token/dashboard/",
    },
  });
  Object.defineProperty(replay, "source", { value: previewWindow });
  globalThis.dispatchEvent(replay);

  expect(syncQuery).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  expect(report).not.toHaveBeenCalled();
  server.dispose();
});

it("preserves document identity through same-view navigation", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const previewWindow = {
    postMessage: vi.fn(),
  };
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: previewWindow,
  });
  const syncQuery = vi.fn();
  const syncEditorQuery = vi.fn(async () => "accepted" as const);
  const report = vi.fn();
  const server = new PreviewController(
    "dashboard",
    "server",
    editor,
    preview,
    (view, runtime, navigation) =>
      `https://studio.test/${view}/?region=emea&marimo_studio_client=client-1&marimo_server_instance=server-1&runtime=${runtime}${navigation?.hash ?? ""}`,
    (view) => `/support/${view}`,
    syncQuery,
    syncEditorQuery,
    vi.fn(),
    report,
    undefined,
    undefined,
    { query: "?region=emea", hash: "" },
    undefined,
    7,
  );
  const previewSource = preview.src;

  server.navigateWithinView({ query: "?region=emea", hash: "#details" });

  expect(syncEditorQuery).not.toHaveBeenCalled();
  expect(syncQuery).not.toHaveBeenCalled();
  expect(preview.src).toBe(previewSource);
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      url: expect.stringContaining("marimo_studio_client=client-1"),
    }),
  );
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:query-change",
    runtime: "server",
    lifecycleId: 7,
    query: "?region=americas",
  });
  expect(syncQuery).toHaveBeenCalledWith("?region=americas");
  server.dispose();
});

const sourceRevisions = {
  "index.html": "sha256:index",
  "app.css": "sha256:style",
} as const;

it("accepts sessionless WASM readiness from the rendered view", () => {
  const editor = frame("loading");
  const preview = frame("complete");
  const report = vi.fn();
  const wasm = controller(
    "wasm",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    report,
  );

  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      status: { diagnostics: [], message: "Live", state: "ready" },
    }),
  );
  wasm.dispose();
});

it.each(["load-first", "message-first"] as const)(
  "lets a self-polling waiting document own slow startup when %s",
  async (order) => {
    vi.useFakeTimers();
    const editor = frame("complete");
    const preview = frame("complete");
    const server = controller(
      "server",
      editor,
      preview,
      (view, runtime) => `/${view}?runtime=${runtime}`,
    );
    const source = preview.src;

    const loaded = () => preview.dispatchEvent(new Event("load"));
    const waiting = () =>
      dispatchPreviewMessage(null, {
        type: "marimo-studio:receiver-waiting",
        runtime: "server",
        lifecycleId: 1,
        view: "dashboard",
      });
    if (order === "load-first") {
      loaded();
      waiting();
    } else {
      waiting();
      loaded();
    }
    await vi.advanceTimersByTimeAsync(10_000);

    expect(preview.src).toBe(source);
    expect(preview.dataset.previewLifecycleId).toBe("1");

    dispatchPreviewMessage(null, {
      type: "marimo-studio:receiver-unready",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
    });
    preview.dispatchEvent(new Event("load"));
    await vi.advanceTimersByTimeAsync(10_000);
    expect(Number(preview.dataset.previewLifecycleId)).toBeGreaterThan(1);
    expect(preview.src).not.toBe(source);
    server.dispose();
  },
);

it("starts WASM control synchronization from an active rendered-view session", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>();
  fetch.mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        schema: 1,
        revision: "revision-1",
        runtime: "server",
        controlRevision: 1,
        controls: { native: { cells: {} } },
      }),
      { headers: { ETag: '"server-controls"', "Content-Type": "application/json" } },
    ),
  );
  fetch.mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        schema: 1,
        revision: "revision-1",
        runtime: "wasm",
        controlRevision: 1,
        controls: { native: { cells: {} } },
      }),
      { headers: { ETag: '"wasm-controls"', "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const editor = frame("loading");
  const preview = frame("complete");
  const previewWindow = createFrameBridgeSource();
  installFrameBridge(preview, previewWindow, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  const connect = vi.fn(() => controlEndpoint());
  const wasm = new PreviewController(
    "dashboard",
    wasmRuntime,
    serverRuntime.id,
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
    undefined,
    connect,
  );
  wasm.editorSessionChanged("s_editor1", false);

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  await vi.waitFor(() => expect(connect).toHaveBeenCalledOnce());
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(
    fetch.mock.calls.every(
      ([, init]) => new Headers(init?.headers).get("Marimo-Session-Id") === "s_editor1",
    ),
  ).toBe(true);
  wasm.dispose();
});

it("suspends hidden WASM ownership and reactivates the same document", async () => {
  const config = (runtime: "server" | "wasm") => ({
    ...runtimeConfig(runtime),
    runtimeBindings: { cellRefs: { controls: `${runtime}-cell` } },
  });
  const fetch = vi
    .fn<typeof globalThis.fetch>()
    .mockResolvedValueOnce(Response.json(config("server")))
    .mockResolvedValueOnce(Response.json(config("wasm")))
    .mockResolvedValueOnce(Response.json(config("server")))
    .mockResolvedValueOnce(Response.json(config("wasm")));
  vi.stubGlobal("fetch", fetch);
  const editor = frame("loading");
  const preview = frame("complete");
  const previewWindow = createFrameBridgeSource();
  const bridgeIdentity = {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  } as const;
  installFrameBridge(preview, previewWindow, bridgeIdentity);
  const hiddenEditorApply = vi.fn(async () => {});
  const editorEndpoint = (apply: ControlEndpoint["apply"]): ControlEndpoint => ({
    snapshot: () => [],
    subscribe: () => () => {},
    apply,
    dispose: vi.fn(),
  });
  const hidden = editorEndpoint(hiddenEditorApply);
  const reactivated = editorEndpoint(vi.fn(async () => {}));
  const connect = vi
    .fn<() => ControlEndpoint | undefined>()
    .mockReturnValueOnce(hidden)
    .mockReturnValueOnce(reactivated);
  const syncQuery = vi.fn();
  const syncEditorQuery = vi.fn(async () => "accepted" as const);
  const recordObservation = vi.fn(async () => undefined);
  const wasm = new PreviewController(
    "dashboard",
    "wasm",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    syncQuery,
    syncEditorQuery,
    vi.fn(),
    vi.fn(),
    recordObservation,
    connect,
    { query: "?canonical=1", hash: "" },
  );
  wasm.editorSessionChanged("s_editor1", false);
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  await vi.waitFor(() => expect(connect).toHaveBeenCalledOnce());
  wasm.requestObservation({
    schema: 1,
    requestId: "hidden-observation",
    view: "dashboard",
    runtime: "wasm",
    runtimeInstance: "wasm-instance",
    revision: "revision-1",
  });
  const documentSource = preview.src;
  const lifecycleId = preview.dataset.previewLifecycleId;

  wasm.deactivate();
  sendFrameControlUpdate(previewWindow, bridgeIdentity, {
    objectId: "wasm-cell-control-0",
    value: 9,
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:query-change",
    runtime: "wasm",
    lifecycleId: 1,
    query: "?hidden=1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    lifecycleId: 1,
    requestId: "hidden-observation",
    view: "dashboard",
    runtime: "wasm",
    runtimeInstance: "wasm-instance",
    revision: "revision-1",
    state: "ready",
    diagnostics: [],
    sessionId: null,
    query: "?hidden=1",
    ...emptyProjectionEvidence,
  });
  await Promise.resolve();

  expect(hiddenEditorApply).not.toHaveBeenCalled();
  expect(syncQuery).not.toHaveBeenCalled();
  expect(syncEditorQuery).not.toHaveBeenCalled();
  expect(recordObservation).not.toHaveBeenCalled();
  expect(hidden.dispose).toHaveBeenCalledOnce();

  const warmActivation = wasm.activate({ query: "?canonical=1", hash: "" });
  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  const activation = Promise.race([
    warmActivation,
    new Promise<never>((_resolve, reject) =>
      setTimeout(() => reject(new Error("Warm WASM activation did not settle")), 1_000),
    ),
  ]);
  await expect(activation).resolves.toBe(true);
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  expect(preview.src).toBe(documentSource);
  expect(preview.dataset.previewLifecycleId).toBe(lifecycleId);
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:frame-query-apply",
      query: "?canonical=1",
    }),
    "*",
  );

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:query-change",
    runtime: "wasm",
    lifecycleId: 1,
    query: "?active=1",
  });
  await vi.waitFor(() => expect(syncEditorQuery).toHaveBeenCalledOnce());
  expect(syncQuery).toHaveBeenCalledWith("?active=1");
  wasm.dispose();
});

it("reports a live control failure and clears it after retry", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<typeof globalThis.fetch>();
  fetch.mockResolvedValueOnce(
    Response.json({
      ...runtimeConfig("server"),
      runtimeBindings: { cellRefs: { controls: "server-cell" } },
    }),
  );
  fetch.mockResolvedValueOnce(
    Response.json({
      ...runtimeConfig("wasm"),
      runtimeBindings: { cellRefs: { controls: "wasm-cell" } },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  let emitEditor: ((update: ControlUpdate) => void) | undefined;
  const editorEndpoint: ControlEndpoint = {
    snapshot: () => [],
    subscribe: (listener) => {
      emitEditor = listener;
      return () => {};
    },
    apply: vi.fn(async () => {}),
    dispose: vi.fn(),
  };
  let controlAttempt = 0;
  const previewWindow = createFrameBridgeSource((message) => {
    if (message.type === "marimo-studio:frame-control-apply" && controlAttempt++ === 0) {
      return "preview kernel unavailable";
    }
  });
  const preview = frame("complete");
  installFrameBridge(preview, previewWindow, {
    lifecycleId: 1,
    revision: "revision-1",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  });
  const connect = vi.fn<() => ControlEndpoint | undefined>().mockReturnValue(editorEndpoint);
  const report = vi.fn();
  const wasm = new PreviewController(
    "dashboard",
    "wasm",
    frame("loading"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    report,
    undefined,
    connect,
  );
  wasm.editorSessionChanged("s_editor1", false);

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  await vi.waitFor(() => expect(connect).toHaveBeenCalledOnce());

  emitEditor?.({ objectId: "server-cell-control-0", value: 4 });
  await vi.waitFor(() =>
    expect(report).toHaveBeenLastCalledWith(
      expect.objectContaining({
        runtimeStatus: expect.objectContaining({
          current: expect.objectContaining({
            phase: "degraded",
            diagnostics: [expect.objectContaining({ code: "control-sync-failed" })],
          }),
        }),
      }),
    ),
  );
  await vi.advanceTimersByTimeAsync(100);
  await vi.waitFor(() =>
    expect(report).toHaveBeenLastCalledWith(
      expect.objectContaining({
        runtimeStatus: expect.objectContaining({
          current: expect.objectContaining({ phase: "ready", diagnostics: [] }),
        }),
      }),
    ),
  );

  wasm.dispose();
});

it("reports a query failure and clears it after the editor recovers", async () => {
  vi.useFakeTimers();
  const syncEditorQuery = vi
    .fn<
      (
        query: string,
        operationId: string,
        writeGeneration: number,
        signal: AbortSignal,
      ) => Promise<EditorQuerySyncResult>
    >()
    .mockRejectedValueOnce(new Error("editor query unavailable"))
    .mockResolvedValueOnce("accepted");
  const report = vi.fn();
  const server = new PreviewController(
    "dashboard",
    "wasm",
    frame("loading"),
    frame("complete"),
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    syncEditorQuery,
    vi.fn(),
    report,
  );
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "wasm",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });

  dispatchPreviewMessage(null, {
    type: "marimo-studio:query-change",
    runtime: "wasm",
    lifecycleId: 1,
    query: "?region=apac",
  });
  await vi.waitFor(() =>
    expect(
      report.mock.calls.some(([state]) =>
        state.runtimeStatus.current.diagnostics.some(
          (diagnostic: BrowserDiagnostic) => diagnostic.code === "query-sync-failed",
        ),
      ),
    ).toBe(true),
  );
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() =>
    expect(report).toHaveBeenLastCalledWith(
      expect.objectContaining({
        runtimeStatus: expect.objectContaining({
          current: expect.objectContaining({ phase: "ready", diagnostics: [] }),
        }),
      }),
    ),
  );

  expect(syncEditorQuery).toHaveBeenCalledTimes(2);
  server.dispose();
});

it("restores the committed query after an editor-session reload interrupts dispatch", async () => {
  let resolveDispatch!: (result: EditorQuerySyncResult) => void;
  const dispatched = new Promise<EditorQuerySyncResult>((resolve) => {
    resolveDispatch = resolve;
  });
  const syncEditorQuery = vi
    .fn<
      (
        query: string,
        operationId: string,
        writeGeneration: number,
        signal: AbortSignal,
      ) => Promise<EditorQuerySyncResult>
    >()
    .mockReturnValueOnce(dispatched)
    .mockResolvedValue("accepted");
  const server = new PreviewController(
    "dashboard",
    "server",
    frame("loading"),
    frame("complete"),
    (view, runtime) => `/${view}?runtime=${runtime}`,
    (view) => `/support/${view}`,
    vi.fn(),
    syncEditorQuery,
    vi.fn(),
    vi.fn(),
    undefined,
    undefined,
    { query: "?region=emea", hash: "" },
  );

  const navigation = server.synchronizeNavigationQuery("?region=apac");
  const operationId = syncEditorQuery.mock.calls[0]?.[1];
  server.editorSessionChanged();
  await expect(navigation).resolves.toBe(false);
  server.editorQueryChanged("?region=apac", operationId, true);
  expect(syncEditorQuery).toHaveBeenCalledOnce();
  resolveDispatch("accepted");
  await vi.waitFor(() => expect(syncEditorQuery).toHaveBeenCalledTimes(2));

  expect(syncEditorQuery.mock.calls[1]?.[0]).toBe("?region=emea");
  server.dispose();
});

it("retires an unavailable runtime and recreates it on the current view", async () => {
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const zeroFrame = frame("complete");
  const availability = vi.fn(async () => ({
    runtimes: ["server", "wasm", "zero-python"],
    revision: "plain-r2",
  }));
  const viewUrl = vi.fn(
    (view: string, runtime: string, revision?: string | null) =>
      `/${view}?runtime=${runtime}${revision ? `&revision=${revision}` : ""}`,
  );
  const deck = new PreviewDeck({
    initialView: "projected",
    initialRuntime: serverRuntime,
    runtimes: [serverRuntime, wasmRuntime, zeroPythonRuntime],
    availableRuntimes: ["server", "wasm", "zero-python"],
    defaultRuntime: "server",
    sourceRevisions,
    presentationRevision: "projected-r1",
    loadRuntimeAvailability: availability,
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
      ["zero-python", zeroFrame],
    ]),
  );
  deck.switchRuntime("zero-python");

  deck.switchView("plain", ["server", "wasm"], sourceRevisions, "plain-r1");
  expect(zeroFrame.src).toBe("about:blank");
  deck.sourceChanged("html", sourceRevisions);
  await vi.waitFor(() =>
    expect(deck.getSnapshot().runtimes.map(({ id }) => id)).toContain("zero-python"),
  );
  deck.switchRuntime("zero-python");

  expect(zeroFrame.src).toContain("/plain?runtime=zero-python&revision=plain-r2");
  expect(availability).toHaveBeenCalledOnce();
  deck.dispose();
});

it("recovers runtime availability after one bounded timeout", async () => {
  vi.useFakeTimers();
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const zeroFrame = frame("complete");
  const availability = vi
    .fn()
    .mockImplementationOnce(async () => await new Promise<never>(() => {}))
    .mockResolvedValue({
      runtimes: ["server", "wasm", "zero-python"],
      revision: "recovered-r2",
    });
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: serverRuntime,
    runtimes: [serverRuntime, wasmRuntime, zeroPythonRuntime],
    availableRuntimes: ["server", "wasm", "zero-python"],
    defaultRuntime: "server",
    sourceRevisions,
    presentationRevision: "dashboard-r1",
    loadRuntimeAvailability: availability,
    viewUrl: (view, runtime, revision) =>
      `/${view}?runtime=${runtime}${revision ? `&revision=${revision}` : ""}`,
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
      ["zero-python", zeroFrame],
    ]),
  );

  deck.sourceChanged("html", sourceRevisions);
  await vi.advanceTimersByTimeAsync(2_000);
  expect(deck.getSnapshot().runtimes.map(({ id }) => id)).toEqual(["server", "wasm"]);
  await vi.advanceTimersByTimeAsync(250);

  expect(deck.getSnapshot().runtimes.map(({ id }) => id)).toEqual([
    "server",
    "wasm",
    "zero-python",
  ]);
  expect(availability).toHaveBeenCalledTimes(2);
  deck.dispose();
});

it("ignores a late runtime availability result after disposal", async () => {
  let release = (_value: { runtimes: string[]; revision: string }) => {};
  const pending = new Promise<{ runtimes: string[]; revision: string }>((resolve) => {
    release = resolve;
  });
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: serverRuntime,
    runtimes: [serverRuntime, wasmRuntime],
    availableRuntimes: ["server", "wasm"],
    defaultRuntime: "server",
    sourceRevisions,
    presentationRevision: "dashboard-r1",
    loadRuntimeAvailability: async () => await pending,
    viewUrl,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  const calls = viewUrl.mock.calls.length;

  deck.sourceChanged("html", sourceRevisions);
  deck.dispose();
  release({ runtimes: ["server", "wasm"], revision: "dashboard-r2" });
  await Promise.resolve();
  await Promise.resolve();

  expect(viewUrl).toHaveBeenCalledTimes(calls);
});

it("disposes later preview controllers after the first cleanup fails", () => {
  const editor = frame("complete");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: serverRuntime,
    runtimes: [serverRuntime, wasmRuntime],
    availableRuntimes: ["server", "wasm"],
    defaultRuntime: "server",
    sourceRevisions,
    presentationRevision: "dashboard-r1",
    loadRuntimeAvailability: async () => ({
      runtimes: ["server", "wasm"],
      revision: "dashboard-r1",
    }),
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
  const original = PreviewController.prototype.dispose;
  let disposals = 0;
  vi.spyOn(PreviewController.prototype, "dispose").mockImplementation(
    function (this: PreviewController) {
      disposals += 1;
      if (disposals === 1) {
        throw new Error("first preview cleanup failed");
      }
      original.call(this);
    },
  );

  expect(() => deck.dispose()).toThrow("first preview cleanup failed");
  expect(disposals).toBe(2);
  expect(() => deck.dispose()).not.toThrow();
});

it("reloads one held preview when its control revision expires", async () => {
  vi.useFakeTimers();
  let editorReads = 0;
  let previewReads = 0;
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const url = new URL(input instanceof Request ? input.url : input, globalThis.location.href);
    const runtime = url.searchParams.get("runtime");
    if (runtime === "server") {
      editorReads += 1;
      if (editorReads > 1) {
        return Response.json(
          {
            error: "presentation-revision-unavailable",
            message: "Presentation revision unavailable",
            transient: true,
          },
          { status: 409 },
        );
      }
    } else {
      previewReads += 1;
      if (previewReads > 1) {
        return new Response(null, { status: 304, headers: { ETag: '"wasm-controls"' } });
      }
    }
    return Response.json(
      {
        schema: 1,
        revision: "revision-1",
        runtime,
        controlRevision: 1,
        controls: { native: { cells: {} } },
      },
      { headers: { ETag: `"${runtime}-controls"` } },
    );
  });
  vi.stubGlobal("fetch", fetch);
  const editor = frame("loading");
  const preview = frame("complete");
  preview.src = "/loaded?marimo_studio_client=browser-client-1234";
  const viewUrl = vi.fn(
    (view: string, runtime: string) =>
      `/${view}?runtime=${runtime}&marimo_studio_client=browser-client-1234`,
  );
  const endpoints = [controlEndpoint(), controlEndpoint()];
  const connect = vi.fn().mockReturnValueOnce(endpoints[0]).mockReturnValueOnce(endpoints[1]);
  const wasm = new PreviewController(
    "dashboard",
    wasmRuntime,
    serverRuntime.id,
    editor,
    preview,
    viewUrl,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
    undefined,
    connect,
  );

  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      data: {
        type: "marimo-studio:view-ready",
        runtime: "wasm",
        view: "dashboard",
        revision: "revision-1",
        sessionId: "s_123456",
      },
    }),
  );
  await vi.waitFor(() => expect(connect).toHaveBeenCalledTimes(2));
  await vi.advanceTimersByTimeAsync(1_000);
  await vi.waitFor(() => expect(viewUrl).toHaveBeenCalledTimes(2));
  const reloads = viewUrl.mock.calls.length;
  await vi.runAllTimersAsync();

  expect(viewUrl).toHaveBeenCalledTimes(reloads);
  expect(endpoints[0]?.dispose).toHaveBeenCalledOnce();
  expect(endpoints[1]?.dispose).toHaveBeenCalledOnce();
  wasm.dispose();
});
