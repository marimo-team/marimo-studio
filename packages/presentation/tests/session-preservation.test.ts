import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import {
  BrowserSessionReplay,
  type SessionEnvironment,
} from "../src/document/session-preservation.ts";
import { symbolicRuntimeFields } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

const config = (preserveSession: boolean, mode: RuntimeConfig["mode"] = "run"): RuntimeConfig => ({
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    descriptor: serverRuntime.descriptor,
    instance: "server-instance",
    data: {
      fileKey: "/workspace/analysis.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode,
});

const wasmConfig = (): RuntimeConfig => ({
  ...config(false),
  runtime: {
    id: "wasm",
    instance: "wasm-instance",
    data: {
      code: "pass",
      filename: "analysis.py",
      version: "1",
      executionCells: [{ id: "bootstrap", code: "pass" }],
      bootstrapCellId: "bootstrap",
    },
  },
});

interface SessionEnvironmentOptions {
  clientId?: string;
  href?: string;
  lifecycleId?: number;
  navigationType?: SessionEnvironment["navigationType"];
  renewalToken?: string;
  replay?: boolean;
  runtimeExplicit?: boolean;
  runtimeSessionId?: string;
}

const environment = (
  storage: Map<string, string>,
  {
    clientId,
    href = "https://example.test/dashboard/",
    lifecycleId,
    navigationType = "navigate",
    renewalToken,
    replay = false,
    runtimeExplicit = new URL(href).searchParams.has("runtime"),
    runtimeSessionId,
  }: SessionEnvironmentOptions = {},
) => {
  const replaced: string[] = [];
  const value: SessionEnvironment = {
    clientId,
    href,
    lifecycleId,
    navigationType,
    renewalToken,
    replay,
    replaceUrl: (url) => replaced.push(url),
    runtimeExplicit,
    runtimeSessionId,
    storage: {
      getItem: (key) => storage.get(key) ?? null,
      removeItem: (key) => storage.delete(key),
      setItem: (key, item) => storage.set(key, item),
    },
  };
  return { value, replaced };
};

const withSessionStorageGetter = (getter: () => Storage, operation: () => void): void => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  if (!descriptor) {
    throw new Error("The test environment does not expose sessionStorage");
  }
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    get: getter,
  });
  try {
    operation();
  } finally {
    Object.defineProperty(globalThis, "sessionStorage", descriptor);
  }
};

const renewalToken = "d.file.dashboard.s_view01.s_abc123.signature";
const signedDocument = (query: string): string =>
  `https://example.test/_marimo-studio/presentation/${renewalToken}/dashboard/${query}`;

test("sandboxed documents treat inaccessible session storage as unavailable", () => {
  const previousUrl = globalThis.location.href;
  globalThis.history.replaceState(
    {},
    "",
    "/dashboard/?runtime=wasm&session_id=s_abc123&marimo_studio_resume=1",
  );
  try {
    withSessionStorageGetter(
      () => {
        throw new DOMException("Storage is unavailable", "SecurityError");
      },
      () => {
        const replay = new BrowserSessionReplay(undefined, () => "s_abc123");

        assert.equal(replay.preflight(config(true)), false);
        assert.equal(globalThis.location.href, "http://localhost:3000/dashboard/");
        assert.equal(replay.pending(), false);
        assert.equal(
          replay.preservedUrl(
            config(true),
            "https://example.test/report/?runtime=wasm" +
              "&session_id=s_abc123&marimo_studio_resume=1",
          ),
          "https://example.test/report/",
        );
        assert.doesNotThrow(() => replay.remember(config(true), "s_abc123"));
        assert.doesNotThrow(() => replay.finish());
      },
    );
  } finally {
    globalThis.history.replaceState({}, "", previousUrl);
  }
});

test("replay preflight canonicalizes explicit runtime on every early exit", () => {
  const cases = [
    { label: "storage unavailable", config: config(true), storage: false },
    { label: "non-server runtime", config: wasmConfig(), storage: true },
    { label: "disabled preservation", config: config(false), storage: true },
    { label: "edit mode", config: config(true, "edit"), storage: true },
  ] as const;

  for (const candidate of cases) {
    const browser = environment(new Map(), {
      href:
        "https://example.test/dashboard/?region=eu&runtime=forged" +
        "&session_id=s_abc123&marimo_studio_resume=1",
      navigationType: "reload",
    });
    if (!candidate.storage) {
      browser.value.storage = undefined;
    }

    assert.equal(
      new BrowserSessionReplay(browser.value).preflight(candidate.config),
      false,
      candidate.label,
    );
    assert.deepEqual(browser.replaced, [
      `https://example.test/dashboard/?region=eu&runtime=${candidate.config.runtime.id}`,
    ]);
  }
});

test("method-level storage denial rejects replay and commits the trusted URL", () => {
  const browser = environment(new Map(), {
    href:
      "https://example.test/dashboard/?region=eu&runtime=forged" +
      "&session_id=s_abc123&marimo_studio_resume=1",
    navigationType: "reload",
  });
  browser.value.storage = {
    getItem: () => {
      throw new DOMException("Storage is unavailable", "SecurityError");
    },
    removeItem: () => undefined,
    setItem: () => undefined,
  };
  const replay = new BrowserSessionReplay(browser.value, () => "s_abc123");

  assert.equal(replay.preflight(config(true)), false);
  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?region=eu&runtime=server"]);
  assert.equal(
    replay.preservedUrl(
      config(true),
      "https://example.test/report/?region=eu&runtime=forged" +
        "&session_id=s_abc123&marimo_studio_resume=1",
    ),
    "https://example.test/report/?region=eu&runtime=server",
  );
});

test("storage denial preserves a markerless signed document session", () => {
  for (const selectedConfig of [config(true), config(true, "edit")]) {
    const browser = environment(new Map(), {
      href: signedDocument("?session_id=s_abc123&runtime=wasm"),
      navigationType: "reload",
      renewalToken,
      runtimeExplicit: false,
      runtimeSessionId: "s_abc123",
    });
    browser.value.storage = undefined;

    assert.equal(new BrowserSessionReplay(browser.value).preflight(selectedConfig), false);
    assert.deepEqual(browser.replaced, [signedDocument("?session_id=s_abc123")]);
  }

  const methodDenied = environment(new Map(), {
    href: signedDocument("?session_id=s_abc123"),
    navigationType: "reload",
    renewalToken,
    runtimeExplicit: false,
    runtimeSessionId: "s_abc123",
  });
  methodDenied.value.storage = {
    getItem: () => {
      throw new DOMException("Storage is unavailable", "SecurityError");
    },
    removeItem: () => undefined,
    setItem: () => undefined,
  };
  assert.equal(new BrowserSessionReplay(methodDenied.value).preflight(config(true)), false);
  assert.deepEqual(methodDenied.replaced, []);
});

test("storage denial preserves exact wrapper-validated signed replay", () => {
  const browser = environment(new Map(), {
    href: signedDocument("?session_id=s_abc123&marimo_studio_resume=1&runtime=wasm"),
    navigationType: "reload",
    renewalToken,
    replay: true,
    runtimeExplicit: false,
    runtimeSessionId: "s_abc123",
  });
  browser.value.storage = undefined;

  assert.equal(new BrowserSessionReplay(browser.value).preflight(config(true)), true);
  assert.deepEqual(browser.replaced, [
    signedDocument("?session_id=s_abc123&marimo_studio_resume=1"),
  ]);
});

test("frozen mount restores private identity before native session bootstrap", () => {
  const browser = environment(new Map(), {
    clientId: "client-123456789",
    href: "https://example.test/dashboard/?region=eu",
    lifecycleId: 7,
    navigationType: "reload",
    renewalToken,
    replay: true,
    runtimeExplicit: false,
    runtimeSessionId: "s_abc123",
  });
  browser.value.storage = undefined;

  assert.equal(new BrowserSessionReplay(browser.value).preflight(config(true)), true);
  assert.deepEqual(browser.replaced, [
    "https://example.test/dashboard/" +
      "?region=eu&marimo_studio_client=client-123456789" +
      "&marimo_studio_lifecycle=7&session_id=s_abc123" +
      "&marimo_studio_resume=1",
  ]);
});

test("signed replay still requires run-mode preservation policy", () => {
  for (const selectedConfig of [config(false), config(true, "edit")]) {
    const browser = environment(new Map(), {
      href: signedDocument("?session_id=s_abc123&marimo_studio_resume=1"),
      navigationType: "reload",
      renewalToken,
      replay: true,
      runtimeExplicit: false,
      runtimeSessionId: "s_abc123",
    });
    browser.value.storage = undefined;

    assert.equal(new BrowserSessionReplay(browser.value).preflight(selectedConfig), false);
    assert.deepEqual(browser.replaced, [signedDocument("")]);
  }
});

test("storage denial rejects replay and caller-supplied session authority", () => {
  const cases = [
    { href: "https://example.test/dashboard/?session_id=s_abc123" },
    {
      href: signedDocument("?session_id=s_abc123&session_id=s_def456"),
    },
    { href: signedDocument("?session_id=malformed") },
    {
      href: signedDocument("?session_id=s_def456&marimo_studio_resume=1"),
    },
  ];

  for (const candidate of cases) {
    const browser = environment(new Map(), {
      href: candidate.href,
      navigationType: "reload",
      runtimeExplicit: false,
    });
    browser.value.storage = undefined;

    assert.equal(new BrowserSessionReplay(browser.value).preflight(config(true)), false);
    const rejected = new URL(candidate.href);
    rejected.search = "";
    assert.deepEqual(browser.replaced, [rejected.href]);
  }
});

test("Studio edit refresh retains its runtime session on the signed renewal document", () => {
  const source = environment(new Map(), {
    clientId: "client-123456789",
    href:
      "https://example.test/html-view/?file=notebook.py" +
      "&marimo_studio_client=client-123456789" +
      "&marimo_studio_lifecycle=4",
    lifecycleId: 4,
    runtimeSessionId: "s_abc123",
  });
  source.value.storage = undefined;
  const replay = new BrowserSessionReplay(source.value, () => "s_def456");
  const editConfig = { ...config(false, "edit"), dev: true };

  assert.equal(
    replay.preservedUrl(
      editConfig,
      "https://example.test/_marimo-studio/presentation/" +
        "d.file.html-view.s_preview.s_abc123.signature/html-view/" +
        "?file=notebook.py&marimo_studio_client=client-123456789" +
        "&marimo_studio_lifecycle=4",
    ),
    "https://example.test/_marimo-studio/presentation/" +
      "d.file.html-view.s_preview.s_abc123.signature/html-view/" +
      "?file=notebook.py&marimo_studio_client=client-123456789" +
      "&marimo_studio_lifecycle=4" +
      "&session_id=s_abc123",
  );
});

test("Studio edit refresh does not attach a runtime session to an unowned document", () => {
  const source = environment(new Map(), {
    clientId: "client-123456789",
    href:
      "https://example.test/html-view/?file=notebook.py" +
      "&marimo_studio_client=client-123456789" +
      "&marimo_studio_lifecycle=4",
    lifecycleId: 4,
  });
  source.value.storage = undefined;
  const replay = new BrowserSessionReplay(source.value, () => "s_abc123");
  const editConfig = { ...config(false, "edit"), dev: true };

  assert.equal(
    replay.preservedUrl(editConfig, "https://example.test/html-view/?file=notebook.py"),
    "https://example.test/html-view/?file=notebook.py",
  );
  assert.equal(
    replay.preservedUrl(
      editConfig,
      "https://other.test/_marimo-studio/presentation/" +
        "d.file.html-view.s_preview.s_abc123.signature/html-view/?file=notebook.py",
    ),
    "https://other.test/_marimo-studio/presentation/" +
      "d.file.html-view.s_preview.s_abc123.signature/html-view/?file=notebook.py",
  );
});

test("session storage failures outside browser access policy remain visible", () => {
  withSessionStorageGetter(
    () => {
      throw new Error("storage adapter failed");
    },
    () => {
      const replay = new BrowserSessionReplay(undefined, () => "s_abc123");
      assert.throws(
        () => replay.preservedUrl(config(true), "https://example.test/report/"),
        /storage adapter failed/,
      );
    },
  );
});

test("WASM navigation omits forged native session state", () => {
  const browser = environment(new Map(), {
    href: "https://example.test/dashboard/?runtime=wasm",
    runtimeExplicit: true,
  });
  const replay = new BrowserSessionReplay(browser.value, () => "s_forged");

  assert.equal(
    replay.preservedUrl(
      wasmConfig(),
      "https://example.test/report/?runtime=server" + "&session_id=s_forged&marimo_studio_resume=1",
    ),
    "https://example.test/report/?runtime=wasm",
  );
});

test("WASM preflight removes query-form renewal authority", () => {
  const browser = environment(new Map(), {
    href:
      "https://example.test/dashboard/?region=eu&runtime=wasm" +
      "&marimo_studio_renewal=forged&session_id=s_forged",
    navigationType: "reload",
    renewalToken,
    runtimeExplicit: true,
  });
  browser.value.storage = undefined;

  assert.equal(new BrowserSessionReplay(browser.value).preflight(wasmConfig()), false);
  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?region=eu&runtime=wasm"]);
});

test("a reload restores the session remembered for its view path", () => {
  const storage = new Map<string, string>();
  const first = environment(storage);
  new BrowserSessionReplay(first.value).remember(config(true), "s_abc123");
  const reload = environment(storage, { navigationType: "reload" });

  const prepared = new BrowserSessionReplay(reload.value).preflight(config(true));

  assert.deepEqual(prepared, true);
  assert.deepEqual(reload.replaced, [
    "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1",
  ]);
});

test("a history return restores the session remembered for its view path", () => {
  const storage = new Map<string, string>();
  const first = environment(storage, {
    href: "https://example.test/dashboard/?region=emea",
  });
  new BrowserSessionReplay(first.value).remember(config(true), "s_abc123");
  const historyReturn = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&runtime=wasm",
    navigationType: "back_forward",
    runtimeExplicit: false,
  });

  const prepared = new BrowserSessionReplay(historyReturn.value).preflight(config(true));

  assert.equal(prepared, true);
  assert.deepEqual(historyReturn.replaced, [
    "https://example.test/dashboard/" + "?region=emea&session_id=s_abc123&marimo_studio_resume=1",
  ]);

  const explicitHistoryReturn = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&runtime=wasm",
    navigationType: "back_forward",
    runtimeExplicit: true,
  });
  assert.equal(new BrowserSessionReplay(explicitHistoryReturn.value).preflight(config(true)), true);
  assert.deepEqual(explicitHistoryReturn.replaced, [
    "https://example.test/dashboard/" +
      "?region=emea&runtime=server&session_id=s_abc123&marimo_studio_resume=1",
  ]);
});

test("a session remains bound to its first public query", () => {
  const storage = new Map<string, string>();
  const browser = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&file=analysis.py",
  });
  const replay = new BrowserSessionReplay(browser.value);
  replay.remember(config(true), "s_abc123");
  browser.value.href =
    "https://example.test/dashboard/?region=apac&file=forged.py&access_token=secret";
  replay.remember(config(true), "s_abc123");

  const changed = environment(storage, {
    href: "https://example.test/dashboard/?region=apac&file=analysis.py",
    navigationType: "reload",
  });
  const original = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&file=analysis.py",
    navigationType: "reload",
  });

  assert.equal(new BrowserSessionReplay(changed.value).preflight(config(true)), false);
  assert.deepEqual(changed.replaced, []);
  assert.equal(new BrowserSessionReplay(original.value).preflight(config(true)), true);
  assert.deepEqual(original.replaced, [
    "https://example.test/dashboard/?region=emea&file=analysis.py" +
      "&session_id=s_abc123&marimo_studio_resume=1",
  ]);
});

test("private transport parameters do not change replay query identity", () => {
  const storage = new Map<string, string>();
  const first = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&file=analysis.py&access_token=old",
  });
  new BrowserSessionReplay(first.value).remember(config(true), "s_abc123");
  const reload = environment(storage, {
    href: "https://example.test/dashboard/?access_token=new&file=other.py&region=emea",
    navigationType: "reload",
  });

  assert.equal(new BrowserSessionReplay(reload.value).preflight(config(true)), true);
});

test("session preservation stays scoped to run-mode reloads and history returns", () => {
  const storage = new Map<string, string>();
  new BrowserSessionReplay(environment(storage).value).remember(config(true), "s_abc123");
  const navigation = environment(storage);
  const otherUI = environment(storage, {
    href: "https://example.test/executive/",
    navigationType: "reload",
  });

  assert.deepEqual(new BrowserSessionReplay(navigation.value).preflight(config(true)), false);
  assert.deepEqual(new BrowserSessionReplay(otherUI.value).preflight(config(true)), false);

  assert.deepEqual(navigation.replaced, []);
  assert.deepEqual(otherUI.replaced, []);

  const disabledStorage = new Map<string, string>();
  const disabled = environment(disabledStorage, { navigationType: "reload" });
  new BrowserSessionReplay(disabled.value).remember(config(false), "s_abc123");
  assert.deepEqual(new BrowserSessionReplay(disabled.value).preflight(config(false)), false);
  assert.deepEqual(disabledStorage.size, 0);
  assert.deepEqual(disabled.replaced, []);

  const editStorage = new Map<string, string>();
  const edit = environment(editStorage, { navigationType: "reload" });
  new BrowserSessionReplay(edit.value).remember(config(true, "edit"), "s_abc123");
  assert.deepEqual(new BrowserSessionReplay(edit.value).preflight(config(true, "edit")), false);
  assert.deepEqual(editStorage.size, 0);
  assert.deepEqual(edit.replaced, []);
});

test("the replay marker is removed after the runtime opens", () => {
  const browser = environment(new Map(), {
    href: "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1&view=summary",
  });

  new BrowserSessionReplay(browser.value).finish();

  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?view=summary"]);
});

test("an intentional document navigation carries runtime and server session", () => {
  const storage = new Map<string, string>();
  const source = environment(storage, {
    href: "https://example.test/dashboard/?region=emea&runtime=server",
  });
  const replay = new BrowserSessionReplay(source.value, () => "s_abc123");
  replay.remember(config(true), "s_abc123");
  const target = replay.preservedUrl(
    config(true),
    "https://example.test/report/?region=emea&runtime=wasm",
  );
  const browser = environment(storage, {
    href: target,
    navigationType: "navigate",
    renewalToken,
    replay: true,
    runtimeSessionId: "s_abc123",
  });

  assert.equal(
    target,
    "https://example.test/report/?region=emea&runtime=server&session_id=s_abc123&marimo_studio_resume=1",
  );
  assert.equal(new BrowserSessionReplay(browser.value).preflight(config(true)), true);

  assert.equal(
    replay.preservedUrl(config(true), "https://example.test/report/?region=apac"),
    "https://example.test/report/?region=apac&runtime=server",
  );
});

test("disabling preservation cancels a pending replay", () => {
  const storage = new Map<string, string>();
  new BrowserSessionReplay(environment(storage).value).remember(config(true), "s_abc123");
  const browser = environment(storage, {
    href: "https://example.test/dashboard/?session_id=s_abc123&marimo_studio_resume=1&view=summary",
    navigationType: "reload",
  });

  assert.deepEqual(new BrowserSessionReplay(browser.value).preflight(config(false)), false);
  assert.deepEqual(browser.replaced, ["https://example.test/dashboard/?view=summary"]);
  assert.deepEqual(storage.size, 0);
});
