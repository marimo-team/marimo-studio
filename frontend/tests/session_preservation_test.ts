import { assertEquals } from "@std/assert";

import type { RuntimeConfig } from "../src/runtime-config.ts";
import {
  finishSessionRefresh,
  prepareSessionRefresh,
  rememberSession,
  type SessionEnvironment,
} from "../src/session-preservation.ts";

const config = (
  preserveSession: boolean,
  mode: RuntimeConfig["mode"] = "run",
): RuntimeConfig => ({
  schema: 1,
  view: "dashboard",
  views: ["dashboard"],
  fileKey: "/workspace/analysis.py",
  runtimeUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {},
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  serverToken: "token",
  dev: false,
  mode,
  preserveSession,
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
      setItem: (key, item) => storage.set(key, item),
    },
  };
  return { value, replaced };
};

Deno.test("a reload restores the session remembered for its view path", () => {
  const storage = new Map<string, string>();
  const first = environment(storage);
  rememberSession(config(true), "s_abc123", first.value);
  const reload = environment(storage, { navigationType: "reload" });

  const prepared = prepareSessionRefresh(config(true), reload.value);

  assertEquals(prepared, true);
  assertEquals(
    reload.replaced,
    [
      "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1",
    ],
  );
});

Deno.test("session preservation stays scoped to a run-mode page reload", () => {
  const storage = new Map<string, string>();
  rememberSession(config(true), "s_abc123", environment(storage).value);
  const navigation = environment(storage);
  const otherUI = environment(storage, {
    href: "https://example.test/executive/",
    navigationType: "reload",
  });

  assertEquals(prepareSessionRefresh(config(true), navigation.value), false);
  assertEquals(prepareSessionRefresh(config(true), otherUI.value), false);

  assertEquals(navigation.replaced, []);
  assertEquals(otherUI.replaced, []);

  const disabledStorage = new Map<string, string>();
  const disabled = environment(disabledStorage, { navigationType: "reload" });
  rememberSession(config(false), "s_abc123", disabled.value);
  assertEquals(prepareSessionRefresh(config(false), disabled.value), false);
  assertEquals(disabledStorage.size, 0);
  assertEquals(disabled.replaced, []);

  const editStorage = new Map<string, string>();
  const edit = environment(editStorage, { navigationType: "reload" });
  rememberSession(config(true, "edit"), "s_abc123", edit.value);
  assertEquals(
    prepareSessionRefresh(config(true, "edit"), edit.value),
    false,
  );
  assertEquals(editStorage.size, 0);
  assertEquals(edit.replaced, []);
});

Deno.test("the replay marker is removed after the runtime opens", () => {
  const browser = environment(new Map(), {
    href: "https://example.test/dashboard/?marimo_studio_resume=1&view=summary",
  });

  finishSessionRefresh(browser.value);

  assertEquals(browser.replaced, [
    "https://example.test/dashboard/?view=summary",
  ]);
});
