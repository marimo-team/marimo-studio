import "./framed-document.ts";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { bindRuntimeQueryHistory, startQuerySync } from "../src/document/query-sync.ts";
import { commitRuntimeConfig, getSupportUrl, setSupportUrl } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
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
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  setActiveDocumentLifecycleId(7);

  startQuerySync();

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:query-change",
      runtime: "wasm",
      lifecycleId: 7,
      query: "",
    },
    globalThis.location.origin,
  );
  globalThis.history.pushState = pushState;
  globalThis.history.replaceState = replaceState;
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
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  setActiveDocumentLifecycleId(7);

  startQuerySync();

  expect(postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      lifecycleId: 7,
      query: "?region=emea",
    },
    globalThis.location.origin,
  );
  globalThis.history.pushState = pushState;
  globalThis.history.replaceState = replaceState;
});

test("an isolated direct view reports public query changes to its wrapper", () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.history.replaceState({}, "", "/?file=notebook.py&region=emea");
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  setActiveDocumentLifecycleId(9);

  startQuerySync();

  expect(parent.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      lifecycleId: 9,
      query: "?region=emea",
    },
    globalThis.location.origin,
  );
  globalThis.history.pushState = pushState;
  globalThis.history.replaceState = replaceState;
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

test("static browser history reloads when query synchronization fails", async () => {
  const updateQuery = vi.fn(async () => {
    throw new Error("query bridge unavailable");
  });
  const reload = vi.fn();
  const dispose = bindRuntimeQueryHistory(updateQuery, reload);

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
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  startQuerySync();
  try {
    globalThis.history.pushState({}, "", "?region=us");
    expect(new URL(globalThis.location.href).searchParams.get("marimo_studio_revision")).toBe(
      "checkpoint",
    );
    globalThis.history.replaceState({}, "", "?region=apac");
    expect(new URL(globalThis.location.href).searchParams.get("marimo_studio_revision")).toBe(
      "checkpoint",
    );
    globalThis.history.pushState({}, "", "/report/?region=apac");
    expect(new URL(globalThis.location.href).searchParams.has("marimo_studio_revision")).toBe(
      false,
    );
  } finally {
    globalThis.history.pushState = pushState;
    globalThis.history.replaceState = replaceState;
  }
});

test("notebook history writes retain admitted editor routing without sending it as public query state", () => {
  const originalSupport = getSupportUrl();
  setSupportUrl("/support/dashboard?marimo_studio_editor_session=s_current");
  globalThis.history.replaceState({}, "", "/dashboard/?region=eu");
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  startQuerySync();
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
    globalThis.history.pushState = pushState;
    globalThis.history.replaceState = replaceState;
    setSupportUrl(originalSupport);
  }
});
