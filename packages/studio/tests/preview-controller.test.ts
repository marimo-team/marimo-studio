import type { JsonValue, RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { afterEach, expect, it, vi } from "vite-plus/test";

import type { ControlEndpoint } from "../src/features/preview/control-sync.ts";

import { PreviewController } from "../src/features/preview/controller.ts";
import { PreviewDeck } from "../src/features/preview/deck.ts";

afterEach(() => vi.unstubAllGlobals());

const frame = (readyState: DocumentReadyState): HTMLIFrameElement => {
  const element = document.createElement("iframe");
  Object.defineProperty(element, "contentDocument", {
    configurable: true,
    value: { readyState },
  });
  Object.defineProperty(element, "contentWindow", {
    configurable: true,
    value: null,
  });
  element.src = "/loaded";
  return element;
};

const controller = (
  runtime: string,
  editor: HTMLIFrameElement,
  preview: HTMLIFrameElement,
  viewUrl: (view: string, runtime: string) => string,
  report = vi.fn(),
) =>
  new PreviewController(
    "dashboard",
    runtime,
    editor,
    preview,
    viewUrl,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    report,
  );

const dispatchPreviewMessage = <Source>(source: Source, data: JsonValue): void => {
  const event = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data,
  });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

const runtimeConfig = (runtime: string) =>
  ({
    schema: 1,
    revision: "revision-1",
    view: "dashboard",
    views: ["dashboard"],
    runtime: {
      id: runtime,
      instance: `${runtime}-instance`,
      available: ["server", "wasm"],
      data: {},
      controls: { cells: {} },
    },
    rootUrl: "/",
    publicRootUrl: "/",
    documentRootUrl: "/",
    supportUrl: "/support/dashboard",
    showCellLogs: true,
    cellBindings: {},
    valueBindings: {},
    outputBindings: {},
    diagnostics: [],
    appConfig: {},
    userConfig: {},
    configOverrides: {},
    editorSessionId: "s_123456",
    dev: true,
    mode: "edit",
  }) satisfies RuntimeConfig;

const controlEndpoint = (): ControlEndpoint => ({
  snapshot: () => [],
  subscribe: () => () => {},
  apply: vi.fn(async () => {}),
  dispose: vi.fn(),
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

  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      data: {
        type: "marimo-studio:view-ready",
        runtime: "wasm",
        view: "dashboard",
        revision: "revision-1",
      },
    }),
  );

  expect(report).toHaveBeenLastCalledWith(
    expect.objectContaining({
      status: { message: "Live", state: "ready", title: "" },
    }),
  );
  wasm.dispose();
});

it("starts WASM control synchronization from an active rendered-view session", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>();
  fetch.mockResolvedValueOnce(Response.json(runtimeConfig("server")));
  fetch.mockResolvedValueOnce(Response.json(runtimeConfig("wasm")));
  vi.stubGlobal("fetch", fetch);
  const editor = frame("loading");
  const preview = frame("complete");
  const connect = vi.fn(() => controlEndpoint());
  const wasm = new PreviewController(
    "dashboard",
    "wasm",
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
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls.map(([, init]) => init?.headers)).toEqual([
    { "Marimo-Session-Id": "s_123456" },
    { "Marimo-Session-Id": "s_123456" },
  ]);
  wasm.dispose();
});

it("reloads every preview after its editor session binding changes", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const server = controller("server", editor, serverFrame, viewUrl);
  const wasm = controller("wasm", editor, wasmFrame, viewUrl);
  expect(viewUrl).toHaveBeenCalledTimes(2);

  editor.dispatchEvent(new Event("load"));
  expect(viewUrl).toHaveBeenCalledTimes(2);
  editor.dispatchEvent(new Event("load"));
  expect(viewUrl).toHaveBeenCalledTimes(2);

  server.editorSessionChanged();
  wasm.editorSessionChanged();

  expect(viewUrl).toHaveBeenCalledTimes(4);
  expect(serverFrame.src).toContain("runtime=server");
  expect(wasmFrame.src).toContain("runtime=wasm");
  server.dispose();
  wasm.dispose();
});

it("refreshes every attached preview on demand", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const serverWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  const wasmWindow = { dispatchEvent: vi.fn(), postMessage: vi.fn() };
  Object.defineProperty(serverFrame, "contentWindow", {
    configurable: true,
    value: serverWindow,
  });
  Object.defineProperty(wasmFrame, "contentWindow", {
    configurable: true,
    value: wasmWindow,
  });
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
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
  deck.switchRuntime("wasm");
  expect(viewUrl).toHaveBeenCalledTimes(4);
  for (const [runtime, source] of [
    ["server", serverWindow],
    ["wasm", wasmWindow],
  ] as const) {
    dispatchPreviewMessage(source, {
      type: "marimo-studio:view-ready",
      runtime,
      view: "dashboard",
      revision: "revision-1",
    });
    expect(deck.runtimeDiagnostics(runtime)?.current.phase).toBe("ready");
  }

  deck.reload();

  expect(viewUrl).toHaveBeenCalledTimes(6);
  expect(serverFrame.src).toContain("runtime=server");
  expect(wasmFrame.src).toContain("runtime=wasm");
  expect(deck.runtimeDiagnostics("server")).toMatchObject({
    revision: null,
    current: { phase: "connecting", diagnostics: [] },
  });
  expect(deck.runtimeDiagnostics("wasm")).toMatchObject({
    revision: null,
    current: { phase: "connecting", diagnostics: [] },
  });
  deck.dispose();
});

it("reconciles source changes across the rendered preview lifecycle", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const postMessage = vi.fn();
  const previewWindow = { postMessage };
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

  server.sourceChanged("runtime");

  expect(postMessage).not.toHaveBeenCalled();
  const ready = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      view: "dashboard",
    },
  });
  Object.defineProperty(ready, "source", { value: previewWindow });
  globalThis.dispatchEvent(ready);

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "html",
    },
    globalThis.location.origin,
  );
  expect(server.runtimeStatus().current.phase).toBe("synchronizing");
  postMessage.mockClear();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });

  server.sourceChanged("css");

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "css",
    },
    globalThis.location.origin,
  );
  postMessage.mockClear();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    view: "dashboard",
  });
  const disconnected = server.runtimeStatus();
  expect(disconnected.revision).toBeNull();
  expect(disconnected.sessionId).toBeNull();
  expect(disconnected.transitions.find(({ phase }) => phase === "ready")).toMatchObject({
    revision: "revision-1",
    sessionId: "s_123456",
  });
  postMessage.mockClear();
  globalThis.dispatchEvent(ready);

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "html",
    },
    globalThis.location.origin,
  );
  server.dispose();
});

it("reconciles source after a soft view switch commits", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const postMessage = vi.fn();
  const previewWindow = { postMessage };
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
  const dispatch = (data: JsonValue) => dispatchPreviewMessage(previewWindow, data);
  dispatch({
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "dashboard",
  });
  dispatch({
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });
  postMessage.mockClear();

  server.switchView("report");
  server.sourceChanged("css");

  expect(postMessage).toHaveBeenCalledOnce();
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:switch-view", view: "report" }),
    globalThis.location.origin,
  );
  dispatch({
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "report",
    revision: "revision-2",
    sessionId: "s_123456",
  });

  expect(postMessage).toHaveBeenLastCalledWith(
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "report",
      kind: "html",
    },
    globalThis.location.origin,
  );
  server.dispose();
});

it("compares the stream baseline with the rendered revision", () => {
  const editor = frame("complete");
  const preview = frame("complete");
  const postMessage = vi.fn();
  const previewWindow = { postMessage };
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
  server.sourceBaseline("revision-1");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    view: "dashboard",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });

  expect(postMessage).not.toHaveBeenCalled();

  server.sourceBaseline("revision-2");

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:source-change",
      runtime: "server",
      view: "dashboard",
      kind: "html",
    },
    globalThis.location.origin,
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
    view: "dashboard",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    view: "dashboard",
    revision: "revision-1",
    sessionId: "s_123456",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-diagnostics",
    runtime: "server",
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
  const record = vi.fn(async () => undefined);
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
  server.requestObservation({
    schema: 1,
    requestId: "stale-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "stale-instance",
    revision: "revision-1",
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
    requestId: "stale-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "stale-instance",
    revision: "revision-1",
    state: "ready",
    diagnostics: [],
    sessionId: "s_stale1",
    query: "",
  });

  expect(report).not.toHaveBeenCalled();
  expect(preview.dataset.sessionId).toBeUndefined();
  expect(server.runtimeStatus()).toMatchObject({
    revision: null,
    sessionId: null,
    current: { phase: "connecting" },
  });

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-observation",
    requestId: "current-request",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "current-instance",
    revision: "revision-2",
    state: "ready",
    diagnostics: [],
    sessionId: "s_current2",
    query: "",
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

it("reloads attached previews once for each newer editor binding", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
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
  deck.switchRuntime("wasm");
  expect(viewUrl).toHaveBeenCalledTimes(4);

  deck.editorSessionChanged({
    schema: 1,
    generation: 7,
    sessionId: "s_initial",
    replaced: false,
  });
  deck.editorSessionChanged({
    schema: 1,
    generation: 6,
    sessionId: "s_stale",
    replaced: false,
  });
  expect(viewUrl).toHaveBeenCalledTimes(4);

  deck.editorSessionChanged({
    schema: 1,
    generation: 8,
    sessionId: "s_reconnected",
    replaced: true,
  });
  expect(viewUrl).toHaveBeenCalledTimes(6);
  expect(serverFrame.src).toContain("runtime=server");
  expect(wasmFrame.src).toContain("runtime=wasm");
  deck.dispose();
});
