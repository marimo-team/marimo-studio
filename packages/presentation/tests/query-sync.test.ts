import "./framed-document.ts";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { bindRuntimeQueryHistory, startQuerySync } from "../src/document/query-sync.ts";
import { commitRuntimeConfig, getSupportUrl, setSupportUrl } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "wasm",
  runtimeExplicit: true,
  replay: false,
  clientId: "client-123456789",
  lifecycleId: 7,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  globalThis.history.replaceState({}, "", "/");
});

test("pre-config query messages use the server-minted mount runtime", () => {
  globalThis.history.replaceState(
    {},
    "",
    "/?runtime=server&marimo_studio_client=studio-client&marimo_studio_lifecycle=7",
  );
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  setActiveDocumentLifecycleId(7);

  const dispose = startQuerySync();

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:location-change",
      runtime: "wasm",
      lifecycleId: 7,
      query: "",
      hash: "",
    },
    globalThis.location.origin,
  );
  dispose();
});

test("query changes carry the current document switch", () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.history.replaceState(
    {},
    "",
    "/?region=emea&marimo_studio_client=studio-client&marimo_studio_lifecycle=7",
  );
  vi.stubGlobal("frameElement", null);
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  setActiveDocumentLifecycleId(7);

  const dispose = startQuerySync();

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:location-change",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
      query: "?region=emea",
      hash: "",
    },
    globalThis.location.origin,
  );
  dispose();
});

test("an isolated direct view reports public query changes to its wrapper", () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.history.replaceState({}, "", "/?file=notebook.py&region=emea");
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  setActiveDocumentLifecycleId(9);

  const dispose = startQuerySync();

  expect(parent.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:location-change",
      runtime: "server",
      lifecycleId: 9,
      view: "dashboard",
      query: "?region=emea",
      hash: "",
    },
    globalThis.location.origin,
  );
  dispose();
});

test("a page's own fragment changes report the view location to its parent", async () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.history.replaceState({}, "", "/dashboard/?region=emea");
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  setActiveDocumentLifecycleId(9);
  const dispose = startQuerySync();
  const reported = (hash: string) => ({
    type: "marimo-studio:location-change",
    runtime: "server",
    lifecycleId: 9,
    view: "dashboard",
    query: "?region=emea",
    hash,
  });
  try {
    globalThis.history.replaceState(null, "", "#/2");
    expect(parent.postMessage).toHaveBeenLastCalledWith(
      reported("#/2"),
      globalThis.location.origin,
    );

    globalThis.location.hash = "#/3";
    await vi.waitFor(() =>
      expect(parent.postMessage).toHaveBeenLastCalledWith(
        reported("#/3"),
        globalThis.location.origin,
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      parent.postMessage.mock.calls.filter(([message]) => message.hash === "#/3"),
    ).toHaveLength(1);
  } finally {
    dispose();
  }
});

test("static browser history restores the public WebAssembly query", async () => {
  globalThis.history.replaceState({}, "", "/report/?region=apac");
  const updateQuery = vi.fn(async () => {});
  const reload = vi.fn();
  const dispose = bindRuntimeQueryHistory(updateQuery, reload);

  globalThis.history.replaceState({}, "", "/report/?region=emea&access_token=secret&runtime=wasm");
  globalThis.dispatchEvent(new PopStateEvent("popstate"));

  await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledWith("?region=emea"));
  expect(reload).not.toHaveBeenCalled();
  dispose();

  globalThis.history.replaceState({}, "", "/report/?region=americas");
  globalThis.dispatchEvent(new PopStateEvent("popstate"));
  expect(updateQuery).toHaveBeenCalledOnce();
});

test("static browser history leaves the runtime query alone on fragment navigations", async () => {
  globalThis.history.replaceState({}, "", "/report/?region=apac");
  const stopSync = startQuerySync();
  const updateQuery = vi.fn(async () => {});
  const dispose = bindRuntimeQueryHistory(updateQuery, vi.fn());
  try {
    globalThis.history.pushState({}, "", "?region=emea");
    globalThis.location.hash = "#details";
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(updateQuery).not.toHaveBeenCalled();

    globalThis.history.go(-2);
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledExactlyOnceWith("?region=apac"));
  } finally {
    dispose();
    stopSync();
  }
});

test("static browser history reloads when query synchronization fails", async () => {
  const updateQuery = vi.fn(async () => {
    throw new Error("query bridge unavailable");
  });
  const reload = vi.fn();
  const dispose = bindRuntimeQueryHistory(updateQuery, reload);

  globalThis.history.replaceState({}, "", "/?region=emea");
  globalThis.dispatchEvent(new PopStateEvent("popstate"));

  await vi.waitFor(() => expect(reload).toHaveBeenCalledOnce());
  dispose();
});

test("notebook query writes preserve the current exact checkpoint without exporting it to other views", () => {
  globalThis.history.replaceState(
    {},
    "",
    "/dashboard/?marimo_studio_revision=checkpoint&region=eu",
  );
  const dispose = startQuerySync();
  try {
    globalThis.history.pushState({}, "", "?region=us");
    expect(new URL(globalThis.location.href).searchParams.get("marimo_studio_revision")).toBe(
      "checkpoint",
    );
    globalThis.history.replaceState({}, "", "?region=apac&marimo_studio_revision=forged");
    expect(new URL(globalThis.location.href).searchParams.get("marimo_studio_revision")).toBe(
      "checkpoint",
    );
    globalThis.history.pushState({}, "", "/report/?region=apac");
    expect(new URL(globalThis.location.href).searchParams.has("marimo_studio_revision")).toBe(
      false,
    );
  } finally {
    dispose();
  }
});

test("notebook history writes retain admitted editor routing without sending it as public query state", () => {
  const originalSupport = getSupportUrl();
  setSupportUrl("/support/dashboard?marimo_studio_editor_session=s_current");
  globalThis.history.replaceState({}, "", "/dashboard/?region=eu");
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const dispose = startQuerySync();
  try {
    globalThis.history.pushState(
      {},
      "",
      "?region=us&marimo_studio_client=forged&marimo_studio_editor_session=s_forged",
    );
    const parameters = new URL(globalThis.location.href).searchParams;
    expect(parameters.get("marimo_studio_client")).toBe("client-123456789");
    expect(parameters.get("marimo_studio_editor_session")).toBe("s_current");
    expect(parent.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "?region=us" }),
      globalThis.location.origin,
    );
  } finally {
    dispose();
    setSupportUrl(originalSupport);
  }
});

test("query synchronization releases its listener and history hooks on disposal", () => {
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  globalThis.history.replaceState({}, "", "/dashboard/?marimo_studio_revision=checkpoint");
  const dispose = startQuerySync();
  dispose();
  parent.postMessage.mockClear();
  globalThis.dispatchEvent(new PopStateEvent("popstate"));
  globalThis.history.pushState({}, "", "?region=eu");
  expect(parent.postMessage).not.toHaveBeenCalled();
  expect(new URL(globalThis.location.href).searchParams.has("marimo_studio_revision")).toBe(false);
});
