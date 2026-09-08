import type { ControlEndpoint } from "@marimo-studio/marimo-frontend/control-endpoint";
import type { FrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";

import { parseFrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { startFrameRuntimeBridge } from "../src/document/frame-runtime-bridge.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  globalThis.history.replaceState({}, "", "/");
});

test("advertises semantic bindings for registered controls in the active snapshot", () => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "test",
    revision: "presentation-revision",
    runtime: "zero-python",
    runtimeExplicit: true,
    replay: false,
    clientId: "browser-client-1234",
    lifecycleId: 4,
  };
  commitRuntimeConfig(
    runtimeConfig({ runtime: { id: "zero-python", instance: "prepared", data: {} } }),
  );
  setActiveDocumentLifecycleId(4);
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const apply = vi.fn<ControlEndpoint["apply"]>(async () => {});
  const endpoint: ControlEndpoint = {
    controlBindings: () => ({
      "current-control": { input: "sport", path: [] },
      "other-state-control": { input: "sport", path: [] },
    }),
    subscribeControlBindings: () => () => {},
    subscribeTopology: () => () => {},
    snapshot: () => [{ objectId: "current-control", value: ["aquatics"] }],
    subscribe: () => () => {},
    apply,
    applyLocal: apply,
    dispose: vi.fn(),
  };
  const stop = startFrameRuntimeBridge(null, {
    connectControlEndpoint: () => endpoint,
    updateRuntimeQuery: vi.fn(async () => {}),
  });
  const ready = parseFrameBridgeMessage(parent.postMessage.mock.calls[0]?.[0]);
  expect(ready?.type).toBe("marimo-studio:frame-bridge-ready");
  if (ready?.type !== "marimo-studio:frame-bridge-ready") throw new Error("Missing frame metadata");
  expect(ready.controlMetadata?.bindings).toEqual({
    "current-control": { input: "sport", path: [] },
  });
  stop();
});

test("uses distinct frame generations when randomUUID is unavailable", async () => {
  const getRandomValues = vi.fn((values: Uint32Array) => {
    values.fill(0);
    return values;
  });
  vi.stubGlobal("crypto", { getRandomValues });
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
    version: "test",
    revision: "presentation-revision",
    runtime: "wasm",
    runtimeExplicit: true,
    replay: false,
    clientId: "client-123456789",
    lifecycleId: 6,
  };
  commitRuntimeConfig(
    runtimeConfig({
      runtime: {
        id: "wasm",
        instance: "wasm-instance",
        data: {},
      },
    }),
  );
  setActiveDocumentLifecycleId(6);
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const applyControls = vi.fn<ControlEndpoint["apply"]>(async () => {});
  const endpoint: ControlEndpoint = {
    controlBindings: () => undefined,
    subscribeControlBindings: () => () => {},
    subscribeTopology: () => () => {},
    snapshot: () => [],
    subscribe: () => () => {},
    apply: applyControls,
    applyLocal: applyControls,
    dispose: vi.fn(),
  };
  const updateRuntimeQuery = vi.fn(async (_query: string) => {});
  const dependencies = {
    connectControlEndpoint: () => endpoint,
    updateRuntimeQuery,
  };

  const stopFirst = startFrameRuntimeBridge(null, dependencies);
  const first = parseFrameBridgeMessage(parent.postMessage.mock.calls[0]?.[0]);
  stopFirst();
  const stopSecond = startFrameRuntimeBridge(null, dependencies);
  const second = parseFrameBridgeMessage(parent.postMessage.mock.calls[1]?.[0]);

  expect(first?.type).toBe("marimo-studio:frame-bridge-ready");
  expect(second?.type).toBe("marimo-studio:frame-bridge-ready");
  if (
    first?.type !== "marimo-studio:frame-bridge-ready" ||
    second?.type !== "marimo-studio:frame-bridge-ready"
  ) {
    throw new Error("The frame bridges did not publish ready messages");
  }
  expect(first?.generation.length).toBeGreaterThanOrEqual(16);
  expect(second?.generation).not.toBe(first?.generation);
  expect(getRandomValues).toHaveBeenCalledTimes(2);

  const identity = {
    generation: second.generation,
    lifecycleId: 6,
    revision: "presentation-revision",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  };
  const dispatch = (data: FrameBridgeMessage) => {
    const event = new MessageEvent("message", {
      data,
      origin: globalThis.location.origin,
    });
    Object.defineProperty(event, "source", { value: parent });
    globalThis.dispatchEvent(event);
  };
  dispatch({
    type: "marimo-studio:frame-control-apply",
    requestId: "stale-control",
    updates: [{ objectId: "wasm-control", value: 1 }],
    ...identity,
    generation: first.generation,
  });
  dispatch({
    type: "marimo-studio:frame-query-apply",
    requestId: "stale-query",
    query: "?region=stale",
    ...identity,
    generation: first.generation,
  });
  await vi.waitFor(() => {
    expect(applyControls).not.toHaveBeenCalled();
    expect(updateRuntimeQuery).not.toHaveBeenCalled();
  });

  dispatch({
    type: "marimo-studio:frame-control-apply",
    requestId: "current-control",
    updates: [{ objectId: "wasm-control", value: 2 }],
    ...identity,
  });
  dispatch({
    type: "marimo-studio:frame-query-apply",
    requestId: "current-query",
    query: "?region=current",
    ...identity,
  });
  await vi.waitFor(() => {
    expect(applyControls).toHaveBeenCalledOnce();
    expect(updateRuntimeQuery).toHaveBeenCalledWith("?region=current");
    expect(publicNotebookQuery(globalThis.location.search)).toBe("?region=current");
  });

  let finishLateQuery = () => {};
  updateRuntimeQuery.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finishLateQuery = resolve;
      }),
  );
  dispatch({
    type: "marimo-studio:frame-query-apply",
    requestId: "late-query",
    query: "?region=late",
    ...identity,
  });
  await vi.waitFor(() => expect(updateRuntimeQuery).toHaveBeenCalledWith("?region=late"));
  dispatch({
    type: "marimo-studio:frame-control-apply",
    requestId: "cancelled-control",
    updates: [{ objectId: "wasm-control", value: 3 }],
    ...identity,
  });
  stopSecond();
  finishLateQuery();
  await Promise.resolve();
  await Promise.resolve();
  expect(applyControls).toHaveBeenCalledOnce();
  expect(publicNotebookQuery(globalThis.location.search)).toBe("?region=current");
  expect(parent.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ requestId: "late-query" }),
    globalThis.location.origin,
  );
});

test("opaque WASM frames synchronize controls and navigation through document identity", async () => {
  const applyControls = vi.fn<ControlEndpoint["apply"]>(async () => {});
  const disposeControls = vi.fn<ControlEndpoint["dispose"]>();
  const updateQuery = vi.fn<(query: string) => Promise<void>>(async () => {});
  const endpoint: ControlEndpoint = {
    controlBindings: () => undefined,
    subscribeControlBindings: () => () => {},
    subscribeTopology: () => () => {},
    snapshot: () => [{ objectId: "wasm-control", value: 1 }],
    subscribe: () => () => {},
    apply: applyControls,
    applyLocal: applyControls,
    dispose: disposeControls,
  };
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
    version: "test",
    revision: "presentation-revision",
    runtime: "wasm",
    runtimeExplicit: true,
    replay: false,
    clientId: "client-123456789",
    lifecycleId: 7,
  };
  commitRuntimeConfig(
    runtimeConfig({
      runtime: {
        id: "wasm",
        instance: "wasm-instance",
        data: {},
      },
    }),
  );
  setActiveDocumentLifecycleId(7);
  globalThis.history.replaceState(
    {},
    "",
    "/dashboard/?marimo_studio_client=studio-client&marimo_studio_lifecycle=7",
  );
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const stop = startFrameRuntimeBridge(null, {
    connectControlEndpoint: () => endpoint,
    updateRuntimeQuery: updateQuery,
  });
  const ready = parseFrameBridgeMessage(parent.postMessage.mock.calls[0]?.[0]);
  expect(ready).toMatchObject({
    type: "marimo-studio:frame-bridge-ready",
    lifecycleId: 7,
    revision: "presentation-revision",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
    controls: [{ objectId: "wasm-control", value: 1 }],
  });
  if (ready?.type !== "marimo-studio:frame-bridge-ready") {
    throw new Error("The frame bridge did not publish its ready message");
  }
  const generation = ready.generation;
  const identity = {
    generation,
    lifecycleId: 7,
    revision: "presentation-revision",
    runtime: "wasm",
    sessionId: null,
    view: "dashboard",
  };
  const dispatch = (data: FrameBridgeMessage) => {
    const event = new MessageEvent("message", {
      data,
      origin: globalThis.location.origin,
    });
    Object.defineProperty(event, "source", { value: parent });
    globalThis.dispatchEvent(event);
  };

  const resized = vi.fn();
  globalThis.addEventListener("resize", resized, { once: true });
  dispatch({ type: "marimo-studio:frame-resize", ...identity });
  expect(resized).toHaveBeenCalledOnce();

  dispatch({
    type: "marimo-studio:frame-query-apply",
    requestId: "query_stale",
    query: "?region=stale",
    ...identity,
    lifecycleId: 6,
  });
  expect(updateQuery).not.toHaveBeenCalled();

  dispatch({
    type: "marimo-studio:frame-control-apply",
    requestId: "control_current",
    updates: [{ objectId: "wasm-control", value: 2 }],
    ...identity,
  });
  await vi.waitFor(() =>
    expect(applyControls).toHaveBeenCalledWith([{ objectId: "wasm-control", value: 2 }]),
  );

  dispatch({
    type: "marimo-studio:frame-query-apply",
    requestId: "query_current",
    query: "?region=emea",
    hash: "#details",
    ...identity,
  });
  await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledWith("?region=emea"));
  expect(publicNotebookQuery(globalThis.location.search)).toBe("?region=emea");
  expect(globalThis.location.hash).toBe("#details");
  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:frame-query-applied",
      requestId: "query_current",
      ...identity,
    }),
    globalThis.location.origin,
  );

  stop();
  expect(disposeControls).toHaveBeenCalledOnce();
});

test("acquires a control endpoint that becomes available after bridge startup", async () => {
  const apply = vi.fn<ControlEndpoint["apply"]>(async () => {});
  const dispose = vi.fn<ControlEndpoint["dispose"]>();
  const endpoint: ControlEndpoint = {
    controlBindings: () => undefined,
    subscribeControlBindings: () => () => {},
    subscribeTopology: () => () => {},
    snapshot: () => [{ objectId: "wasm-control", value: 1 }],
    subscribe: () => () => {},
    apply,
    applyLocal: apply,
    dispose,
  };
  const connect = vi.fn<() => ControlEndpoint | undefined>();
  connect.mockReturnValueOnce(undefined).mockReturnValue(endpoint);
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
    version: "test",
    revision: "presentation-revision",
    runtime: "wasm",
    runtimeExplicit: true,
    replay: false,
    clientId: "client-123456789",
    lifecycleId: 9,
  };
  commitRuntimeConfig(
    runtimeConfig({
      runtime: {
        id: "wasm",
        instance: "wasm-instance",
        data: {},
      },
    }),
  );
  setActiveDocumentLifecycleId(9);
  globalThis.history.replaceState(
    {},
    "",
    "/dashboard/?marimo_studio_client=studio-client&marimo_studio_lifecycle=9",
  );
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const stop = startFrameRuntimeBridge(null, {
    connectControlEndpoint: connect,
    updateRuntimeQuery: vi.fn(async () => {}),
  });
  const ready = parseFrameBridgeMessage(parent.postMessage.mock.calls[0]?.[0]);
  expect(ready).toMatchObject({
    type: "marimo-studio:frame-bridge-ready",
    controls: [],
  });
  if (ready?.type !== "marimo-studio:frame-bridge-ready") {
    throw new Error("The frame bridge did not publish its ready message");
  }
  document.dispatchEvent(new Event("marimo-studio:runtime-ready"));
  const available = parseFrameBridgeMessage(parent.postMessage.mock.calls.at(-1)?.[0]);
  expect(available).toMatchObject({
    type: "marimo-studio:frame-bridge-ready",
    generation: ready.generation,
    controlMetadata: { cells: expect.any(Object) },
  });
  const event = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:frame-control-apply",
      generation: ready.generation,
      requestId: "control-late",
      updates: [{ objectId: "wasm-control", value: 2 }],
      lifecycleId: 9,
      revision: "presentation-revision",
      runtime: "wasm",
      sessionId: null,
      view: "dashboard",
    } satisfies FrameBridgeMessage,
  });
  Object.defineProperty(event, "source", { value: parent });
  globalThis.dispatchEvent(event);

  await vi.waitFor(() =>
    expect(apply).toHaveBeenCalledWith([{ objectId: "wasm-control", value: 2 }]),
  );
  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:frame-control-applied",
      requestId: "control-late",
    }),
    globalThis.location.origin,
  );
  expect(connect).toHaveBeenCalledTimes(2);
  stop();
  expect(dispose).toHaveBeenCalledOnce();
  const announcements = parent.postMessage.mock.calls.length;
  document.dispatchEvent(new Event("marimo-studio:runtime-ready"));
  expect(parent.postMessage).toHaveBeenCalledTimes(announcements);
});
