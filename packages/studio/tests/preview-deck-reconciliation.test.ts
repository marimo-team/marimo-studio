import { afterEach, expect, it, vi } from "vite-plus/test";

import {
  controller,
  dispatchPreviewMessage,
  dispatchPreviewRefreshHandshake,
  frame,
  previewDeck,
} from "./preview-test-support.ts";

afterEach(() => vi.unstubAllGlobals());

it("reconciles published presentations across the rendered preview lifecycle", () => {
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

  server.presentationChanged();

  expect(postMessage).not.toHaveBeenCalled();
  const ready = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:receiver-ready",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-1",
    },
  });
  Object.defineProperty(ready, "source", { value: previewWindow });
  globalThis.dispatchEvent(ready);

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
    },
    "*",
  );
  expect(server.runtimeStatus().current.phase).toBe("synchronizing");
  postMessage.mockClear();
  dispatchPreviewRefreshHandshake(previewWindow, {
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

  server.presentationChanged();

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
    },
    "*",
  );
  postMessage.mockClear();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-unready",
    runtime: "server",
    lifecycleId: 1,
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
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-1",
    },
    "*",
  );
  server.dispose();
});

it("admits a matching receiver after its presentation build settles", () => {
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
  server.presentationBuildStarted();
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-refresh",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      phase: "pending",
    },
    "*",
  );
  postMessage.mockClear();
  server.presentationBaseline("revision-current");
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });

  expect(postMessage).not.toHaveBeenCalled();

  server.presentationBuildCompleted("revision-current");

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-refresh",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      phase: "settled",
    },
    "*",
  );
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-current",
    },
    "*",
  );
  postMessage.mockClear();
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-current",
    },
    "*",
  );
  server.dispose();
});

it("revokes cached readiness until the built revision is admitted", async () => {
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
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });
  await expect(server.waitUntilReady()).resolves.toBe(true);

  server.presentationBuildStarted();
  const ready = server.waitUntilReady();
  let settled = false;
  void ready.then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);

  server.presentationBuildCompleted("revision-next");
  await Promise.resolve();
  expect(settled).toBe(false);
  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-next",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-next",
  });

  await expect(ready).resolves.toBe(true);
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-next",
    },
    "*",
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
  server.presentationBaseline("revision-1");
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

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
      revision: "revision-1",
    },
    "*",
  );
  postMessage.mockClear();

  server.presentationBaseline("revision-2");

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
    },
    "*",
  );
  server.dispose();
});

it("refreshes a receiver superseded before runtime readiness", async () => {
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
  server.presentationBaseline("revision-current");
  const ready = server.waitUntilReady();
  let settled = false;
  void ready.then(() => {
    settled = true;
  });

  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-superseded",
  });

  await Promise.resolve();
  expect(settled).toBe(false);
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 1,
      view: "dashboard",
    },
    "*",
  );

  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId: 1,
    view: "dashboard",
    revision: "revision-current",
  });

  await expect(ready).resolves.toBe(true);
  server.dispose();
});

it("refreshes when publication advances after receiver readiness", async () => {
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
  const ready = server.activate({ query: "", hash: "" }, undefined, true);
  const lifecycleId = Number(preview.dataset.previewLifecycleId);
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:receiver-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-superseded",
  });
  let settled = false;
  void ready.then(() => {
    settled = true;
  });
  await Promise.resolve();
  expect(settled).toBe(false);

  server.presentationChanged();
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId,
      view: "dashboard",
    },
    "*",
  );
  previewWindow.postMessage.mockClear();

  server.presentationBaseline("revision-current");
  expect(previewWindow.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId,
      view: "dashboard",
    },
    "*",
  );
  dispatchPreviewRefreshHandshake(previewWindow, {
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-current",
  });
  dispatchPreviewMessage(previewWindow, {
    type: "marimo-studio:view-ready",
    runtime: "server",
    lifecycleId,
    view: "dashboard",
    revision: "revision-current",
  });

  await expect(ready).resolves.toBe(true);
  server.dispose();
});

it("reloads only the active preview for a newer editor binding", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const deck = previewDeck({
    runtimes: ["server", "wasm"],
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  deck.switchRuntime("wasm");
  const initialSources = { server: serverFrame.src, wasm: wasmFrame.src };
  const initialLifecycles = {
    server: deck.getSnapshot().states.server?.lifecycleId,
    wasm: deck.getSnapshot().states.wasm?.lifecycleId,
  };
  const initialServerDiagnostics = deck.runtimeDiagnostics("server");

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
  expect({ server: serverFrame.src, wasm: wasmFrame.src }).toEqual(initialSources);
  expect({
    server: deck.getSnapshot().states.server?.lifecycleId,
    wasm: deck.getSnapshot().states.wasm?.lifecycleId,
  }).toEqual(initialLifecycles);
  expect(deck.runtimeDiagnostics("server")).toEqual(initialServerDiagnostics);

  deck.editorSessionChanged({
    schema: 1,
    generation: 8,
    sessionId: "s_reconnected",
    replaced: true,
  });
  expect(serverFrame.src).toBe(initialSources.server);
  expect(wasmFrame.src).not.toBe(initialSources.wasm);
  expect(wasmFrame.src).toContain("runtime=wasm");
  expect(deck.getSnapshot().states.server?.lifecycleId).toBe(initialLifecycles.server);
  expect(deck.getSnapshot().states.wasm?.lifecycleId).toBeGreaterThan(initialLifecycles.wasm ?? 0);
  expect(deck.runtimeDiagnostics("server")).toEqual(initialServerDiagnostics);
  deck.dispose();
});
