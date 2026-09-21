import type { BrowserDiagnostic } from "@marimo-studio/protocol/runtime-status";

import { afterEach, expect, it, vi } from "vite-plus/test";

import type { ControlEndpoint, ControlUpdate } from "../src/features/preview/control-sync.ts";
import type { EditorQuerySyncResult } from "../src/features/preview/query-remote.ts";

import { PreviewController } from "../src/features/preview/controller.ts";
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
    Response.json({ schema: 1, revision: "revision-1", controls: { cells: {} } }),
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
    "wasm",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}&marimo_studio_client=browser-client-1234`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
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
  expect(fetch).toHaveBeenCalledOnce();
  expect(
    fetch.mock.calls.every(
      ([, init]) => new Headers(init?.headers).get("Marimo-Session-Id") === "s_editor1",
    ),
  ).toBe(true);
  wasm.dispose();
});

it("suspends hidden WASM ownership and reactivates the same document", async () => {
  const config = {
    schema: 1,
    revision: "revision-1",
    controls: { cells: { controls: "server-cell" } },
  };
  const fetch = vi
    .fn<typeof globalThis.fetch>()
    .mockResolvedValueOnce(Response.json(config))
    .mockResolvedValueOnce(Response.json(config));
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
  const wasm = new PreviewController(
    "dashboard",
    "wasm",
    editor,
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}&marimo_studio_client=browser-client-1234`,
    (view) => `/support/${view}`,
    syncQuery,
    syncEditorQuery,
    vi.fn(),
    vi.fn(),
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
  await Promise.resolve();

  expect(hiddenEditorApply).not.toHaveBeenCalled();
  expect(syncQuery).not.toHaveBeenCalled();
  expect(syncEditorQuery).not.toHaveBeenCalled();
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
      schema: 1,
      revision: "revision-1",
      controls: { cells: { controls: "server-cell" } },
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
  installFrameBridge(
    preview,
    previewWindow,
    {
      lifecycleId: 1,
      revision: "revision-1",
      runtime: "wasm",
      sessionId: null,
      view: "dashboard",
    },
    [],
    { cells: { controls: "wasm-cell" } },
  );
  const connect = vi.fn<() => ControlEndpoint | undefined>().mockReturnValue(editorEndpoint);
  const report = vi.fn();
  const wasm = new PreviewController(
    "dashboard",
    "wasm",
    frame("loading"),
    preview,
    (view, runtime) => `/${view}?runtime=${runtime}&marimo_studio_client=browser-client-1234`,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    report,
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

it("retains rendered content through a failed refresh until the document is reloaded", () => {
  const report = vi.fn();
  const server = controller(
    "server",
    frame("loading"),
    frame("complete"),
    (view, runtime) => `/${view}?runtime=${runtime}`,
    report,
  );
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ rendered: true }));
  dispatchPreviewMessage(null, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
  });
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-error",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    diagnostic: {
      code: "refresh-failed",
      severity: "error",
      scope: "presentation",
      view: "dashboard",
      message: "The replacement could not be prepared.",
      hint: "Check the view source.",
    },
  });
  expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ rendered: true }));
  server.reload();
  expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ rendered: false }));
  server.dispose();
});

it("accepts current runtime progress without changing readiness and rejects retired documents", () => {
  const report = vi.fn();
  const preview = controller(
    "custom-runtime",
    frame("loading"),
    frame("complete"),
    (view, runtime) => `/${view}?runtime=${runtime}`,
    report,
  );
  const message = {
    type: "marimo-studio:view-progress" as const,
    runtime: "custom-runtime",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
    progress: { message: "Loading model", completed: 3, total: 8 },
  };
  dispatchPreviewMessage(null, message);
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      progress: { message: "Loading model", completed: 3, total: 8 },
      runtimeStatus: expect.objectContaining({ current: { phase: "connecting", diagnostics: [] } }),
    }),
  );
  report.mockClear();
  dispatchPreviewMessage(null, { ...message, view: "another-view" });
  dispatchPreviewMessage(null, { ...message, runtime: "another-runtime" });
  expect(report).not.toHaveBeenCalled();
  dispatchPreviewMessage(null, { ...message, progress: { message: "Checking model" } });
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      progress: { message: "Checking model" },
    }),
  );
  dispatchPreviewMessage(null, { ...message, progress: null });
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({ progress: { message: 'Connecting to runtime "custom-runtime"' } }),
  );
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-ready",
    runtime: "custom-runtime",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-1",
  });
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({ progress: null, rendered: true }),
  );
  report.mockClear();
  dispatchPreviewMessage(null, message);
  expect(report).not.toHaveBeenCalled();
  preview.reload();
  report.mockClear();
  dispatchPreviewMessage(null, message);
  expect(report).not.toHaveBeenCalled();
  preview.dispose();
});

it("retires measurements when the source revision changes or preparation fails", () => {
  const report = vi.fn();
  const preview = controller(
    "custom-runtime",
    frame("loading"),
    frame("complete"),
    (view) => `/${view}`,
    report,
  );
  preview.presentationBaseline("revision-1");
  const message = {
    type: "marimo-studio:view-progress" as const,
    runtime: "custom-runtime",
    view: "dashboard",
    lifecycleId: 1,
    revision: "revision-1",
    progress: { message: "Preparing", completed: 3, total: 8 },
  };
  dispatchPreviewMessage(null, message);
  preview.presentationChanged("revision-2");
  expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ progress: null }));
  report.mockClear();
  dispatchPreviewMessage(null, message);
  expect(report).not.toHaveBeenCalled();
  dispatchPreviewMessage(null, {
    ...message,
    revision: "revision-2",
    progress: { message: "Inspecting replacement" },
  });
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({ progress: { message: "Inspecting replacement" } }),
  );
  dispatchPreviewMessage(null, {
    type: "marimo-studio:view-error",
    runtime: "custom-runtime",
    view: "dashboard",
    lifecycleId: 1,
    diagnostic: {
      code: "preparation-failed",
      message: "Preparation failed.",
      hint: "Retry preview.",
      severity: "error",
      scope: "runtime",
      view: "dashboard",
    },
  });
  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      progress: null,
      status: expect.objectContaining({ state: "error" }),
    }),
  );
  preview.dispose();
});

it.each(["active", "deactivated", "replaced"] as const)(
  "reports document activation timeout only for its active lifecycle: %s",
  async (state) => {
    vi.useFakeTimers();
    const report = vi.fn();
    const server = controller(
      "server",
      frame("complete"),
      frame("complete"),
      (view, runtime) => `/${view}?runtime=${runtime}`,
      report,
    );
    try {
      server.activateDocument({ query: "", hash: "" });
      if (state === "deactivated") server.deactivate();
      if (state === "replaced") server.reload();
      await vi.advanceTimersByTimeAsync(100_000);
      const failures = report.mock.calls
        .flatMap(([snapshot]) => snapshot.status.diagnostics)
        .filter((diagnostic) => diagnostic.code === "preview-activation-failed");
      expect(failures.length > 0).toBe(state === "active");
    } finally {
      server.dispose();
    }
  },
);

it.each(["document", "rendered"] as const)(
  "does not report a superseded document activation when another %s activation owns the same lifecycle",
  async (milestone) => {
    vi.useFakeTimers();
    const report = vi.fn();
    const preview = frame("complete");
    const server = controller(
      "server",
      frame("complete"),
      preview,
      (view, runtime) => `/${view}?runtime=${runtime}`,
      report,
    );
    try {
      server.activateDocument({ query: "", hash: "" });
      const lifecycle = preview.dataset.previewLifecycleId;
      const replacement =
        milestone === "document"
          ? server.activateDocument({ query: "", hash: "" })
          : server.activate({ query: "", hash: "" });
      await vi.advanceTimersByTimeAsync(0);
      expect(preview.dataset.previewLifecycleId).toBe(lifecycle);
      const activationFailures = () =>
        report.mock.calls
          .flatMap(([snapshot]) => snapshot.status.diagnostics)
          .filter((diagnostic) => diagnostic.code === "preview-activation-failed");
      expect(activationFailures()).toEqual([]);
      await vi.advanceTimersByTimeAsync(100_000);
      expect(activationFailures().length > 0).toBe(milestone === "document");
      if (replacement) await expect(replacement).resolves.toBe(false);
    } finally {
      server.dispose();
    }
  },
);

it("preserves the reported runtime failure when document activation ends unsuccessfully", async () => {
  vi.useFakeTimers();
  const report = vi.fn();
  const server = controller(
    "server",
    frame("complete"),
    frame("complete"),
    (view, runtime) => `/${view}?runtime=${runtime}`,
    report,
  );
  const diagnostic = {
    code: "preparation-failed",
    message: "The view build failed.",
    hint: "Fix the view source.",
    severity: "error" as const,
    scope: "runtime" as const,
    view: "dashboard",
  };
  try {
    server.activateDocument({ query: "", hash: "" });
    dispatchPreviewMessage(null, {
      type: "marimo-studio:view-error",
      runtime: "server",
      view: "dashboard",
      lifecycleId: 1,
      diagnostic,
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(report).toHaveBeenLastCalledWith(
      expect.objectContaining({
        status: expect.objectContaining({ state: "error", diagnostics: [diagnostic] }),
      }),
    );
  } finally {
    server.dispose();
  }
});
