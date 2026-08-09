import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import {
  finishSessionRefresh,
  preservedDocumentUrl,
  prepareSessionRefresh,
  rememberSession,
  type SessionEnvironment,
} from "../src/document/session-preservation.ts";

const config = (preserveSession: boolean, mode: RuntimeConfig["mode"] = "run"): RuntimeConfig => ({
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server"],
    data: {
      fileKey: "/workspace/analysis.py",
      serverToken: "token",
      preserveSession,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  showCellLogs: true,
  cellBindings: {},
  valueBindings: {},
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode,
});

const environment = (
  storage: Map<string, string>,
  {
    href = "https://example.test/dashboard/",
    navigationType = "navigate",
  }: {
    href?: string;
    navigationType?: SessionEnvironment["navigationType"];
  } = {},
) => {
  const replaced: string[] = [];
  const value: SessionEnvironment = {
    href,
    navigationType,
    replaceUrl: (url) => replaced.push(url),
    storage: {
      getItem: (key) => storage.get(key) ?? null,
      removeItem: (key) => storage.delete(key),
      setItem: (key, item) => storage.set(key, item),
    },
  };
  return { value, replaced };
};

test("a reload restores the session remembered for its view path", () => {
  const storage = new Map<string, string>();
  const first = environment(storage);
  rememberSession(config(true), "s_abc123", first.value);
  const reload = environment(storage, { navigationType: "reload" });

  const prepared = prepareSessionRefresh(config(true), reload.value);

  assert.deepEqual(prepared, true);
  assert.deepEqual(reload.replaced, [
    "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1",
  ]);
});

test("session preservation stays scoped to a run-mode page reload", () => {
  const storage = new Map<string, string>();
  rememberSession(config(true), "s_abc123", environment(storage).value);
  const navigation = environment(storage);
  const otherUI = environment(storage, {
    href: "https://example.test/executive/",
    navigationType: "reload",
  });

  assert.deepEqual(prepareSessionRefresh(config(true), navigation.value), false);
  assert.deepEqual(prepareSessionRefresh(config(true), otherUI.value), false);

  assert.deepEqual(navigation.replaced, []);
  assert.deepEqual(otherUI.replaced, []);

  const disabledStorage = new Map<string, string>();
  const disabled = environment(disabledStorage, { navigationType: "reload" });
  rememberSession(config(false), "s_abc123", disabled.value);
  assert.deepEqual(prepareSessionRefresh(config(false), disabled.value), false);
  assert.deepEqual(disabledStorage.size, 0);
  assert.deepEqual(disabled.replaced, []);

  const editStorage = new Map<string, string>();
  const edit = environment(editStorage, { navigationType: "reload" });
  rememberSession(config(true, "edit"), "s_abc123", edit.value);
  assert.deepEqual(prepareSessionRefresh(config(true, "edit"), edit.value), false);
  assert.deepEqual(editStorage.size, 0);
  assert.deepEqual(edit.replaced, []);
});

test("the replay marker is removed after the runtime opens", () => {
  const browser = environment(new Map(), {
    href: "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1&view=summary",
  });

  finishSessionRefresh(browser.value);

  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?view=summary"]);
});

test("an intentional document navigation carries runtime and server session", () => {
  const target = preservedDocumentUrl(
    config(true),
    "https://example.test/report/?region=emea",
    "s_abc123",
    "https://example.test/dashboard/?runtime=server",
  );
  const browser = environment(new Map(), {
    href: target,
    navigationType: "navigate",
  });

  assert.equal(
    target,
    "https://example.test/report/?region=emea&runtime=server&session_id=s_abc123&marimo_studio_resume=1",
  );
  assert.equal(prepareSessionRefresh(config(true), browser.value), true);
});

test("disabling preservation cancels a pending replay", () => {
  const storage = new Map([
    ["marimo-studio:session:v1:server:/workspace/analysis.py:/dashboard/", "s_abc123"],
  ]);
  const browser = environment(storage, {
    href: "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1&view=summary",
    navigationType: "reload",
  });

  assert.deepEqual(prepareSessionRefresh(config(false), browser.value), false);
  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?view=summary"]);
  assert.deepEqual(storage.size, 0);
});
