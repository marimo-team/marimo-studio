import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  commitRuntimeConfig,
  fetchCurrentRuntimeConfig,
  fetchRuntimeConfig,
  fetchRuntimeConfigForRevision,
  fetchRuntimeConfigWithRetry,
  getRuntimeCellRefs,
  getRuntimeConfig,
  getRuntimeProjectionConfig,
  loadRuntimeConfig,
  readResponseError,
  type RuntimeConfig,
  RuntimeConfigRequestError,
  runtimeConfigSessionId,
  subscribeRuntimeCellRefs,
  subscribeRuntimeProjectionConfig,
} from "../src/runtime-config/index.ts";
import { serverRuntimeDataSchema } from "../src/runtime/server-config.ts";
import { wasmRuntimeDataSchema } from "../src/runtime/wasm-config.ts";
import { symbolicRuntimeFields } from "./runtime-fixtures.ts";

const baseRuntimeConfig = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard", "executive"],
  runtime: {
    descriptor: serverRuntime.descriptor,
    instance: "server-instance",
    data: {
      fileKey: "/workspace/notebook.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/proxy/app/",
    },
  },
  rootUrl: "/proxy/app/",
  publicRootUrl: "/proxy/app/",
  documentRootUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: true,
  mode: "edit",
} satisfies RuntimeConfig;

const runtimeConfig = (revision: string): RuntimeConfig => ({
  ...baseRuntimeConfig,
  revision,
});

const wasmRuntimeConfig = (): RuntimeConfig => ({
  ...runtimeConfig("presentation-revision"),
  runtime: {
    id: "wasm",
    instance: "wasm-instance",
    data: {
      code: "pass",
      filename: "notebook.py",
      version: "1",
      executionCells: [{ id: "bootstrap", code: "pass" }],
      bootstrapCellId: "bootstrap",
    },
  },
});

const requestUrl = (input: RequestInfo | URL): string =>
  input instanceof URL ? input.href : new Request(input).url;

test("runtime provider data rejects unknown fields", () => {
  assert.equal(
    serverRuntimeDataSchema.safeParse({ ...baseRuntimeConfig.runtime.data, unexpected: true })
      .success,
    false,
  );
  assert.equal(
    wasmRuntimeDataSchema.safeParse({
      code: "pass",
      filename: "notebook.py",
      version: "1",
      executionCells: [{ id: "bootstrap", code: "pass" }],
      bootstrapCellId: "bootstrap",
      unexpected: true,
    }).success,
    false,
  );
});

test("WebAssembly runtime data binds one bootstrap cell to its execution catalog", () => {
  const data = {
    code: "pass",
    filename: "notebook.py",
    version: "1",
    executionCells: [
      { id: "projected", code: "projected = 1" },
      { id: "bootstrap", code: "register_bridge()" },
    ],
    bootstrapCellId: "bootstrap",
  };

  assert.equal(wasmRuntimeDataSchema.safeParse(data).success, true);
  assert.equal(
    wasmRuntimeDataSchema.safeParse({ ...data, bootstrapCellId: "missing" }).success,
    false,
  );
  assert.equal(
    wasmRuntimeDataSchema.safeParse({
      ...data,
      executionCells: [...data.executionCells, data.executionCells[0]],
    }).success,
    false,
  );
});

test("bootstrap uses the server-minted mount runtime before config loads", async () => {
  const originalFetch = globalThis.fetch;
  const previousUrl = globalThis.location.href;
  const lifetime = new AbortController();
  let requestedRuntime: string | null = null;
  let requestSignal: AbortSignal | null | undefined;
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "test-version",
    revision: "presentation-revision",
    runtime: "wasm",
    runtimeExplicit: true,
    replay: false,
  };
  globalThis.history.replaceState({}, "", "/dashboard/?runtime=server");
  globalThis.fetch = (input, init) => {
    requestedRuntime = new URL(requestUrl(input)).searchParams.get("runtime");
    requestSignal = init?.signal;
    return Promise.resolve(Response.json(wasmRuntimeConfig()));
  };

  try {
    const loaded = await loadRuntimeConfig(undefined, lifetime.signal);
    assert.equal(loaded.runtime.id, "wasm");
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.history.replaceState({}, "", previousUrl);
  }

  assert.equal(requestedRuntime, "wasm");
  assert.equal(requestSignal, lifetime.signal);
});

test("session restoration keeps the document revision", async () => {
  const originalFetch = globalThis.fetch;
  let requestedRevision: string | null = null;
  globalThis.fetch = (input) => {
    requestedRevision = new URL(requestUrl(input)).searchParams.get("revision");
    return Promise.resolve(Response.json(runtimeConfig("newer-revision")));
  };

  try {
    const error = await fetchRuntimeConfigForRevision(
      "/_marimo-studio/views/dashboard",
      "presentation-revision",
    ).catch((cause: unknown) => cause);
    assert.ok(error instanceof RuntimeConfigRequestError);
    assert.match(error.message, /one source revision/);
    assert.deepEqual(error.code, "presentation-revision-mismatch");
    assert.deepEqual(error.transient, true);
    assert.deepEqual(requestedRevision, "presentation-revision");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("revision refresh keeps the trusted runtime across mutable history", async () => {
  const originalFetch = globalThis.fetch;
  const previousUrl = globalThis.location.href;
  let requestedRuntime: string | null = null;
  globalThis.history.replaceState({}, "", "/dashboard/?runtime=wasm");
  globalThis.fetch = (input) => {
    requestedRuntime = new URL(requestUrl(input)).searchParams.get("runtime");
    return Promise.resolve(Response.json(runtimeConfig("presentation-revision")));
  };

  try {
    const refreshed = await fetchRuntimeConfigForRevision(
      "/_marimo-studio/views/dashboard",
      "presentation-revision",
      undefined,
      "server",
      undefined,
      undefined,
    );
    assert.equal(refreshed.runtime.id, "server");
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.history.replaceState({}, "", previousUrl);
  }

  assert.equal(requestedRuntime, "server");
});

test("renewal config retries the complete document and config transaction", async () => {
  const originalFetch = globalThis.fetch;
  const lifetime = new AbortController();
  const revisions = ["revision-old", "revision-current"];
  const requested = new Array<string>();
  const requestSignals = new Array<AbortSignal | null | undefined>();
  globalThis.fetch = (input, init) => {
    requestSignals.push(init?.signal);
    const url = requestUrl(input);
    if (init?.method === "HEAD") {
      const revision = revisions.shift() ?? "revision-current";
      return Promise.resolve(
        new Response(null, { headers: { "Marimo-Studio-Revision": revision } }),
      );
    }
    const revision = new URL(url).searchParams.get("revision") ?? "";
    requested.push(revision);
    return Promise.resolve(
      Response.json(
        revision === "revision-old"
          ? {
              error: "presentation-revision-unavailable",
              message: "The requested presentation revision is no longer available.",
              transient: true,
            }
          : runtimeConfig("revision-current"),
        { status: revision === "revision-old" ? 409 : 200 },
      ),
    );
  };

  try {
    const config = await fetchCurrentRuntimeConfig(
      "http://localhost/_marimo-studio/presentation/d.token/dashboard/",
      "http://localhost/_marimo-studio/presentation/d.token/_marimo-studio/views/dashboard",
      "server",
      "s_view01",
      "s_runtime",
      lifetime.signal,
    );
    assert.equal(config.revision, "revision-current");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requested, ["revision-old", "revision-current"]);
  assert.equal(requestSignals.length, 4);
  assert.equal(
    requestSignals.every((signal) => signal === lifetime.signal),
    true,
  );
});

test("fetchRuntimeConfig reports the configuration diagnostic", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () =>
    Promise.resolve(
      new Response(
        JSON.stringify({
          error: "notebook-source-error",
          message: "Marimo cannot inspect the notebook while a cell contains invalid code.",
          hint: "Fix the highlighted cell in Marimo, then save it again.",
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

  try {
    const error = await fetchRuntimeConfig("/_marimo-studio/views/dashboard").catch(
      (cause: unknown) => cause,
    );
    assert.ok(error instanceof RuntimeConfigRequestError);
    assert.match(
      error.message,
      /Marimo cannot inspect the notebook while a cell contains invalid code/,
    );
    assert.deepEqual(error.code, "notebook-source-error");
    assert.deepEqual(error.hint, "Fix the highlighted cell in Marimo, then save it again.");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("HTML error documents do not leak into diagnostics", async () => {
  const detail = await readResponseError(
    new Response("<!doctype html><script>location.reload()</script>", {
      status: 500,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    }),
    "Presentation refresh failed with 500",
  );

  assert.deepEqual(detail.message, "Presentation refresh failed with 500");
});

test("runtime refresh targets frozen mount identity", async () => {
  const originalFetch = globalThis.fetch;
  const previousSession = globalThis.__MARIMO_STUDIO_SESSION_ID__;
  const previousUrl = globalThis.location.href;
  let sessionHeader: string | null = null;
  let previewSessionHeader: string | null = null;
  let requestUrl = "";
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_live12";
  globalThis.history.replaceState({}, "", "/dashboard/?marimo_studio_client=forged-client");
  globalThis.fetch = (input, init) => {
    const headers = new Headers(init?.headers);
    sessionHeader = headers.get("Marimo-Session-Id");
    previewSessionHeader = headers.get("Marimo-Studio-Preview-Session-Id");
    requestUrl = input instanceof URL ? input.href : new Request(input).url;
    return Promise.resolve(Response.json(baseRuntimeConfig));
  };

  try {
    await fetchRuntimeConfig(
      "/_marimo-studio/views/dashboard",
      undefined,
      undefined,
      "s_view01",
      undefined,
      undefined,
      {
        clientId: "browser-client-1234",
        runtime: "server",
        runtimeSessionId: "s_abc123",
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.__MARIMO_STUDIO_SESSION_ID__ = previousSession;
    globalThis.history.replaceState({}, "", previousUrl);
  }

  assert.deepEqual(sessionHeader, "s_abc123");
  assert.deepEqual(previewSessionHeader, "s_view01");
  assert.deepEqual(
    new URL(requestUrl).searchParams.get("marimo_studio_client"),
    "browser-client-1234",
  );
});

test("runtime config targets the frozen mount session", () => {
  assert.deepEqual(
    runtimeConfigSessionId({
      mounted: "s_abc123",
      server: true,
    }),
    "s_abc123",
  );
  assert.deepEqual(runtimeConfigSessionId({ mounted: undefined, server: true }), undefined);
  assert.deepEqual(
    runtimeConfigSessionId({
      connected: "s_live12",
      mounted: "s_abc123",
      server: true,
    }),
    "s_abc123",
  );
  assert.deepEqual(
    runtimeConfigSessionId({ connected: "s_forged", mounted: undefined, server: false }),
    undefined,
  );
});

test("runtime config retries a transient session mismatch", async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = () => {
    attempts += 1;
    return Promise.resolve(
      attempts === 1
        ? Response.json(
            {
              error: "runtime-sync-pending",
              message: "The Marimo session is still connecting.",
              transient: true,
            },
            { status: 409 },
          )
        : Response.json(baseRuntimeConfig),
    );
  };

  try {
    await fetchRuntimeConfigWithRetry("/_marimo-studio/views/dashboard");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(attempts, 2);
});

test("fixed revision rejects an unavailable snapshot without retrying it", async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = () => {
    attempts += 1;
    return Promise.resolve(
      Response.json(
        {
          error: "presentation-revision-unavailable",
          message: "The requested presentation revision is no longer available.",
          transient: true,
        },
        { status: 409 },
      ),
    );
  };

  try {
    const error = await fetchRuntimeConfigForRevision(
      "/_marimo-studio/views/dashboard",
      "retired-revision",
    ).catch((cause: unknown) => cause);
    assert.ok(error instanceof RuntimeConfigRequestError);
    assert.deepEqual(error.code, "presentation-revision-unavailable");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(attempts, 1);
});

test("runtime config retries a failed network request", async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = () => {
    attempts += 1;
    return attempts === 1
      ? Promise.reject(new TypeError("Failed to fetch"))
      : Promise.resolve(Response.json(baseRuntimeConfig));
  };

  try {
    await fetchRuntimeConfigWithRetry("/_marimo-studio/views/dashboard");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(attempts, 2);
});

test("presentation commits advance current config while projection consumers follow their epoch", () => {
  commitRuntimeConfig(baseRuntimeConfig);
  const initial = getRuntimeCellRefs();
  const initialTargets = getRuntimeConfig().projectionTargets;
  const initialProjectionConfig = getRuntimeProjectionConfig();
  let cellCalls = 0;
  let projectionCalls = 0;
  const unsubscribeCells = subscribeRuntimeCellRefs(() => cellCalls++);
  const unsubscribeProjection = subscribeRuntimeProjectionConfig(() => projectionCalls++);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    revision: "presentation-revision-2",
    view: "executive",
    supportUrl: "/proxy/app/_marimo-studio/views/executive",
  });

  assert.equal(getRuntimeConfig().revision, "presentation-revision-2");
  assert.strictEqual(getRuntimeProjectionConfig(), initialProjectionConfig);
  assert.strictEqual(getRuntimeCellRefs(), initial);
  assert.strictEqual(getRuntimeConfig().projectionTargets, initialTargets);
  assert.deepEqual(cellCalls, 0);
  assert.deepEqual(projectionCalls, 0);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    projectionRevision: "b".repeat(64),
    runtimeBindings: { cellRefs: { "cell:v1:plot": "next-cell-id" } },
  });

  assert.deepEqual(cellCalls, 1);
  assert.deepEqual(projectionCalls, 1);
  assert.equal(getRuntimeProjectionConfig().projectionRevision, "b".repeat(64));
  unsubscribeCells();
  unsubscribeProjection();
});
