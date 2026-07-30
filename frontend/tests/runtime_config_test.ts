import {
  assertEquals,
  assertRejects,
  assertStrictEquals,
  assertThrows,
} from "@std/assert";

import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  fetchRuntimeConfigWithRetry,
  getRuntimeCellBindings,
  getRuntimeConfig,
  parseRuntimeConfig,
  type RuntimeConfig,
  runtimeConfigSessionId,
  subscribeRuntimeCellBindings,
} from "../src/runtime-config.ts";

const baseRuntimeConfig = {
  schema: 1,
  view: "dashboard",
  views: ["dashboard", "executive"],
  fileKey: "/workspace/notebook.py",
  runtimeUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  cellBindings: {
    plot: { kind: "name", value: "plot" },
  },
  valueBindings: {
    "context.label": {
      variable: "context",
      cell: { kind: "id", value: "context-cell-id" },
    },
  },
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  serverToken: "server-token",
  dev: true,
  mode: "edit",
  preserveSession: false,
} satisfies RuntimeConfig;

const runtimeConfig = (
  overrides: Record<string, unknown> = {},
): Record<string, unknown> => ({
  ...baseRuntimeConfig,
  ...overrides,
});

Deno.test("parseRuntimeConfig accepts the browser contract", () => {
  assertEquals(parseRuntimeConfig(runtimeConfig()), baseRuntimeConfig);
});

Deno.test("parseRuntimeConfig rejects malformed server contracts", () => {
  const { preserveSession: _, ...missingPolicy } = baseRuntimeConfig;
  const malformed = [
    runtimeConfig({ cellBindings: { plot: { kind: "index", value: "plot" } } }),
    runtimeConfig({
      valueBindings: {
        "context.label": {
          variable: "context",
          cell: { kind: "id", value: 42 },
        },
      },
    }),
    runtimeConfig({ mode: "preview" }),
    runtimeConfig({ view: 42 }),
    runtimeConfig({ views: ["dashboard", 42] }),
    missingPolicy,
    runtimeConfig({ preserveSession: "yes" }),
  ];

  malformed.forEach((config) => {
    assertThrows(() => parseRuntimeConfig(config));
  });
});

Deno.test("fetchRuntimeConfig reports the configuration diagnostic", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () =>
    Promise.resolve(
      new Response(
        JSON.stringify({
          error: "configuration-error",
          message: 'index.html: expected one element with id="app-shell"',
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

  try {
    await assertRejects(
      () => fetchRuntimeConfig("/_marimo-studio/views/dashboard"),
      Error,
      'index.html: expected one element with id="app-shell"',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

Deno.test("runtime refresh targets the connected Marimo session", async () => {
  const originalFetch = globalThis.fetch;
  const browser = globalThis as typeof globalThis & Window;
  const previousSession = browser.__MARIMO_STUDIO_SESSION_ID__;
  let sessionHeader: string | null = null;
  browser.__MARIMO_STUDIO_SESSION_ID__ = "s_abc123";
  globalThis.fetch = (_input, init) => {
    sessionHeader = new Headers(init?.headers).get("Marimo-Session-Id");
    return Promise.resolve(Response.json(baseRuntimeConfig));
  };

  try {
    await fetchRuntimeConfig("/_marimo-studio/views/dashboard");
  } finally {
    globalThis.fetch = originalFetch;
    browser.__MARIMO_STUDIO_SESSION_ID__ = previousSession;
  }

  assertEquals(sessionHeader, "s_abc123");
});

Deno.test("a resumed document targets its remembered session", () => {
  assertEquals(
    runtimeConfigSessionId({
      href: "https://example.test/?session_id=s_abc123&marimo_studio_resume=1",
    }),
    "s_abc123",
  );
  assertEquals(
    runtimeConfigSessionId({
      href: "https://example.test/?session_id=s_new123",
    }),
    undefined,
  );
  assertEquals(
    runtimeConfigSessionId({
      connected: "s_live12",
      href: "https://example.test/?session_id=s_abc123&marimo_studio_resume=1",
    }),
    "s_live12",
  );
});

Deno.test("runtime config retries a transient session mismatch", async () => {
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

  assertEquals(attempts, 2);
});

Deno.test("cell subscribers observe alias mapping changes", () => {
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

  assertStrictEquals(getRuntimeCellBindings(), initial);
  assertStrictEquals(getRuntimeConfig().valueBindings, initialValues);
  assertEquals(calls, 0);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    cellBindings: {
      plot: { kind: "id", value: "next-cell-id" },
    },
  });

  assertEquals(calls, 1);
  unsubscribe();
});
