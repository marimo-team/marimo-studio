import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import assert from "node:assert/strict";
import { afterEach, beforeEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import {
  DevelopmentEvents,
  bindFragmentRestores,
  bindPresentationEvents,
  bindViewNavigation,
} from "../src/document/events.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

class EventSourceStub extends EventTarget {
  static instances: EventSourceStub[] = [];
  closed = false;

  constructor(readonly url: string) {
    super();
    EventSourceStub.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data?: string): void {
    this.dispatchEvent(data === undefined ? new Event(type) : new MessageEvent(type, { data }));
  }
}

interface CyclicPresentationProbe {
  readonly type: "marimo-studio:presentation-refresh";
  readonly runtime: "server";
  readonly lifecycleId: number;
  readonly view: "dashboard";
  readonly phase: "pending";
  self?: CyclicPresentationProbe;
}

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
  document.body.replaceChildren();
});

afterEach(() => {
  globalThis.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

test("closed development streams ignore late events", () => {
  const ready = vi.fn();
  const changed = vi.fn();
  const events = new DevelopmentEvents();
  events.connect("/first", ready, changed);
  const first = EventSourceStub.instances[0];

  events.connect("/second", ready, changed);
  const second = EventSourceStub.instances[1];
  first?.emit("ready");
  first?.emit("change", JSON.stringify({ kind: "project" }));

  assert.equal(first?.closed, true);
  assert.equal(ready.mock.calls.length, 0);
  assert.equal(changed.mock.calls.length, 0);

  second?.emit("ready");
  second?.emit("change", JSON.stringify({ kind: "presentation" }));
  assert.equal(ready.mock.calls.length, 1);
  assert.deepEqual(changed.mock.calls, [[]]);

  events.close();
  second?.emit("ready");
  assert.equal(second?.closed, true);
  assert.equal(ready.mock.calls.length, 1);
});

test("embedded same-view links delegate query and hash navigation to Studio", () => {
  setActiveDocumentLifecycleId(7);
  globalThis.history.replaceState(
    {},
    "",
    "/?marimo_studio_client=client-123&marimo_studio_lifecycle=7",
  );
  commitRuntimeConfig(runtimeConfig());
  const postMessage = vi.fn();
  vi.stubGlobal("parent", { postMessage });
  const direct = vi.fn();
  const dispose = bindViewNavigation(direct, false);
  const anchor = document.createElement("a");
  anchor.href = "/proxy/app/dashboard/?region=emea#details";
  document.body.append(anchor);

  const click = new MouseEvent("click", {
    bubbles: true,
    button: 0,
    cancelable: true,
  });
  anchor.dispatchEvent(click);

  expect(click.defaultPrevented).toBe(true);
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      query: "?region=emea",
      hash: "#details",
    },
    globalThis.location.origin,
  );
  expect(direct).not.toHaveBeenCalled();
  dispose();
});

test("standalone navigation trusts the active runtime and scrubs private query", () => {
  globalThis.history.replaceState({}, "", "/proxy/app/dashboard/?region=emea");
  commitRuntimeConfig(runtimeConfig({ dev: false, views: ["dashboard", "report"] }));
  const direct = vi.fn();
  const dispose = bindViewNavigation(direct, false);
  const forged = document.createElement("a");
  forged.href =
    "/proxy/app/report/?region=emea&runtime=wasm&access_token=forged" +
    "&session_id=s_forged&marimo_studio_client=forged#details";
  const absent = document.createElement("a");
  absent.href = "/proxy/app/report/?region=emea#summary";
  document.body.append(forged, absent);

  forged.dispatchEvent(
    new MouseEvent("click", {
      bubbles: true,
      button: 0,
      cancelable: true,
    }),
  );
  absent.dispatchEvent(
    new MouseEvent("click", {
      bubbles: true,
      button: 0,
      cancelable: true,
    }),
  );

  expect(direct.mock.calls).toEqual([
    [
      {
        documentUrl: "http://localhost:3000/proxy/app/report/?region=emea#details",
        view: "report",
      },
    ],
    [
      {
        documentUrl: "http://localhost:3000/proxy/app/report/?region=emea#summary",
        view: "report",
      },
    ],
  ]);
  dispose();
});

test("static documents leave fragments, queries, and sibling links to the browser", () => {
  globalThis.history.replaceState({}, "", "/published/site/field/index.html?region=emea");
  commitRuntimeConfig(
    runtimeConfig({
      dev: false,
      presentationSessionId: undefined,
      publicRootUrl: "./",
      documentRootUrl: "./",
      view: "field",
      views: ["field", "summary"],
    }),
  );
  const direct = vi.fn();
  const dispose = bindViewNavigation(direct, false);
  const links = ["#details", "?region=apac", "../summary/index.html"];
  const intercepted: boolean[] = [];
  const preventBrowserNavigation = (event: MouseEvent) => {
    intercepted.push(event.defaultPrevented);
    event.preventDefault();
  };
  document.addEventListener("click", preventBrowserNavigation);

  for (const href of links) {
    const anchor = document.createElement("a");
    anchor.setAttribute("href", href);
    document.body.append(anchor);
    const click = new MouseEvent("click", {
      bubbles: true,
      button: 0,
      cancelable: true,
    });

    anchor.dispatchEvent(click);
  }
  expect(intercepted).toEqual([false, false, false]);
  expect(direct).not.toHaveBeenCalled();
  document.removeEventListener("click", preventBrowserNavigation);
  dispose();
});

test("direct wrapper navigation commits in the child before pushing public history", async () => {
  setActiveDocumentLifecycleId(8);
  globalThis.history.replaceState({}, "", "/proxy/app/dashboard/?region=emea&runtime=server");
  commitRuntimeConfig(runtimeConfig({ dev: false, views: ["dashboard", "report"] }));
  const postMessage = vi.fn();
  vi.stubGlobal("parent", { postMessage });
  const direct = vi.fn().mockResolvedValue(true);
  const dispose = bindViewNavigation(direct, true);
  const anchor = document.createElement("a");
  anchor.setAttribute("href", "../report/index.html?region=emea#details");
  document.body.append(anchor);

  const click = new MouseEvent("click", {
    bubbles: true,
    button: 0,
    cancelable: true,
  });
  anchor.dispatchEvent(click);
  await vi.waitFor(() => expect(postMessage).toHaveBeenCalledOnce());

  expect(click.defaultPrevented).toBe(true);
  expect(direct).toHaveBeenCalledWith({
    documentUrl: "http://localhost:3000/proxy/app/report/?region=emea&runtime=server#details",
    view: "report",
  });
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 8,
      view: "report",
      query: "?region=emea&runtime=server",
      hash: "#details",
      history: "push",
    },
    globalThis.location.origin,
  );
  setActiveDocumentLifecycleId(7);
  dispose();
});

test("direct wrapper fragment links scroll and push public history without a view fetch", () => {
  setActiveDocumentLifecycleId(9);
  globalThis.history.replaceState({}, "", "/proxy/app/dashboard/?runtime=server");
  commitRuntimeConfig(runtimeConfig({ dev: false }));
  const postMessage = vi.fn();
  vi.stubGlobal("parent", { postMessage });
  const direct = vi.fn();
  const dispose = bindViewNavigation(direct, true);
  const target = document.createElement("section");
  target.id = "details";
  target.scrollIntoView = vi.fn();
  const anchor = document.createElement("a");
  anchor.href = "#details";
  document.body.append(anchor, target);

  anchor.click();

  expect(direct).not.toHaveBeenCalled();
  expect(target.scrollIntoView).toHaveBeenCalledOnce();
  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:navigate-view",
      runtime: "server",
      lifecycleId: 9,
      view: "dashboard",
      query: "?runtime=server",
      hash: "#details",
      history: "push",
    },
    globalThis.location.origin,
  );
  setActiveDocumentLifecycleId(7);
  dispose();
});

test("wrapper popstate restores a fragment without a presentation transition", () => {
  setActiveDocumentLifecycleId(10);
  commitRuntimeConfig(runtimeConfig({ dev: false }));
  const parent = {};
  vi.stubGlobal("parent", parent);
  const target = document.createElement("section");
  target.id = "restored";
  target.scrollIntoView = vi.fn();
  document.body.append(target);
  const dispose = bindFragmentRestores();
  const event = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:restore-fragment",
      runtime: "server",
      lifecycleId: 10,
      hash: "#restored",
    },
  });
  Object.defineProperty(event, "source", { value: parent });

  globalThis.dispatchEvent(event);

  expect(target.scrollIntoView).toHaveBeenCalledOnce();
  expect(globalThis.location.hash).toBe("#restored");
  setActiveDocumentLifecycleId(7);
  dispose();
});

test("presentation refresh events target the current document lifecycle", async () => {
  globalThis.history.replaceState({}, "", "/?marimo_studio_lifecycle=7");
  commitRuntimeConfig(runtimeConfig());
  const parent = {};
  vi.stubGlobal("parent", parent);
  const changed = vi.fn();
  const refresh = vi.fn();
  const barrier = vi.fn((_port: MessagePort, _generation: number, _signal: AbortSignal) => {});
  const dispose = bindPresentationEvents({ changed, refresh, barrier });
  const dispatch = (data: JsonValue, ports: MessagePort[] = []) => {
    const event = new MessageEvent("message", {
      origin: globalThis.location.origin,
      data,
      ports,
    });
    Object.defineProperty(event, "source", { value: parent });
    globalThis.dispatchEvent(event);
  };

  dispatch({
    type: "marimo-studio:presentation-change",
    runtime: "server",
    view: "dashboard",
  });
  dispatch({
    type: "marimo-studio:presentation-change",
    runtime: "server",
    lifecycleId: 6,
    view: "dashboard",
  });
  expect(changed).not.toHaveBeenCalled();
  dispatch({
    type: "marimo-studio:presentation-change",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
  });
  expect(changed).toHaveBeenCalledOnce();
  dispatch({
    type: "marimo-studio:presentation-refresh",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
    phase: "pending",
  });
  dispatch({
    type: "marimo-studio:presentation-refresh",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
    phase: "settled",
  });
  expect(refresh.mock.calls).toEqual([["pending"], ["settled"]]);
  const channel = new MessageChannel();
  const port = channel.port1;
  dispatch(
    {
      type: "marimo-studio:presentation-refresh-barrier",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      generation: 4,
    },
    [port],
  );
  expect(barrier.mock.calls[0]?.[0]).toBe(port);
  expect(barrier.mock.calls[0]?.[1]).toBe(4);
  const barrierSignal = barrier.mock.calls[0]?.[2];
  expect(barrierSignal.aborted).toBe(false);
  channel.port2.postMessage({
    schema: 1,
    type: "marimo-studio:presentation-refresh-barrier-failed",
    generation: 4,
  });
  await vi.waitFor(() => expect(barrierSignal.aborted).toBe(true));
  dispatch({
    type: "marimo-studio:presentation-refresh-barrier",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
    generation: 5,
  });
  expect(barrier).toHaveBeenCalledOnce();
  channel.port1.close();
  channel.port2.close();
  dispose();
});

test("presentation events bound hostile structured-clone data before recursive parsing", () => {
  setActiveDocumentLifecycleId(7);
  commitRuntimeConfig(runtimeConfig());
  const parent = {};
  vi.stubGlobal("parent", parent);
  const refresh = vi.fn();
  const dispose = bindPresentationEvents({ changed: vi.fn(), refresh });
  const payload: CyclicPresentationProbe = {
    type: "marimo-studio:presentation-refresh",
    runtime: "server",
    lifecycleId: 7,
    view: "dashboard",
    phase: "pending",
  };
  payload.self = payload;
  const browserErrors = vi.fn((event: ErrorEvent) => event.preventDefault());
  globalThis.addEventListener("error", browserErrors);
  const event = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: payload,
  });
  Object.defineProperty(event, "source", { value: parent });

  try {
    globalThis.dispatchEvent(event);
  } finally {
    globalThis.removeEventListener("error", browserErrors);
    dispose();
  }

  expect(browserErrors).not.toHaveBeenCalled();
  expect(refresh).not.toHaveBeenCalled();
});
