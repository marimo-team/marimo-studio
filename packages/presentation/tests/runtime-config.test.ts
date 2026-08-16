import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  fetchRuntimeConfigForRevision,
  fetchRuntimeConfigWithRetry,
  getRuntimeCellBindings,
  getRuntimeConfig,
  readResponseError,
  type RuntimeConfig,
  RuntimeConfigRequestError,
  runtimeConfigSessionId,
  subscribeRuntimeCellBindings,
} from "../src/runtime-config/index.ts";

const baseRuntimeConfig = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard", "executive"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server", "wasm"],
    data: {
      fileKey: "/workspace/notebook.py",
      serverToken: "server-token",
      preserveSession: false,
      url: "/proxy/app/",
    },
  },
  rootUrl: "/proxy/app/",
  publicRootUrl: "/proxy/app/",
  documentRootUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  showCellLogs: true,
  cellBindings: {
    plot: { kind: "name", value: "plot" },
  },
  valueBindings: {
    "context.label": {
      variable: "context",
      cell: { kind: "id", value: "context-cell-id" },
    },
  },
  outputBindings: {},
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

const requestUrl = (input: RequestInfo | URL): string =>
  input instanceof URL ? input.href : new Request(input).url;

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
    "Shell refresh failed with 500",
  );

  assert.deepEqual(detail.message, "Shell refresh failed with 500");
});

test("runtime refresh targets the connected Marimo session", async () => {
  const originalFetch = globalThis.fetch;
  const previousSession = globalThis.__MARIMO_STUDIO_SESSION_ID__;
  const previousUrl = globalThis.location.href;
  let sessionHeader: string | null = null;
  let previewSessionHeader: string | null = null;
  let requestUrl = "";
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_abc123";
  globalThis.history.replaceState({}, "", "/dashboard/?marimo_studio_client=browser-client-1234");
  globalThis.fetch = (input, init) => {
    const headers = new Headers(init?.headers);
    sessionHeader = headers.get("Marimo-Session-Id");
    previewSessionHeader = headers.get("Marimo-Studio-Preview-Session-Id");
    requestUrl = input instanceof URL ? input.href : new Request(input).url;
    return Promise.resolve(Response.json(baseRuntimeConfig));
  };

  try {
    await fetchRuntimeConfig("/_marimo-studio/views/dashboard", undefined, undefined, "s_view01");
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

test("a resumed document targets its remembered session", () => {
  assert.deepEqual(
    runtimeConfigSessionId({
      href: "https://example.test/?session_id=s_abc123&marimo_studio_resume=1",
    }),
    "s_abc123",
  );
  assert.deepEqual(
    runtimeConfigSessionId({
      href: "https://example.test/?session_id=s_new123",
    }),
    undefined,
  );
  assert.deepEqual(
    runtimeConfigSessionId({
      connected: "s_live12",
      href: "https://example.test/?session_id=s_abc123&marimo_studio_resume=1",
    }),
    "s_live12",
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

test("cell subscribers observe alias mapping changes", () => {
  commitRuntimeConfig(baseRuntimeConfig);
  const initial = getRuntimeCellBindings();
  const initialValues = getRuntimeConfig().valueBindings;
  let calls = 0;
  const unsubscribe = subscribeRuntimeCellBindings(() => calls++);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    view: "executive",
    supportUrl: "/proxy/app/_marimo-studio/views/executive",
    cellBindings: {
      plot: { kind: "name", value: "plot" },
    },
  });

  assert.strictEqual(getRuntimeCellBindings(), initial);
  assert.strictEqual(getRuntimeConfig().valueBindings, initialValues);
  assert.deepEqual(calls, 0);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    cellBindings: {
      plot: { kind: "id", value: "next-cell-id" },
    },
  });

  assert.deepEqual(calls, 1);
  unsubscribe();
});
