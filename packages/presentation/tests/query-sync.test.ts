import { afterEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { startQuerySync } from "../src/document/query-sync.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
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
