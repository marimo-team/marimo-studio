import {
  assertEquals,
  assertRejects,
  assertStrictEquals,
  assertThrows,
} from "@std/assert";

import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getRuntimeCells,
  parseRuntimeConfig,
  type RuntimeConfig,
  subscribeRuntimeCells,
} from "../src/runtime-config.ts";

const baseRuntimeConfig = {
  schema: 1,
  view: "dashboard",
  views: ["dashboard", "executive"],
  fileKey: "/workspace/notebook.py",
  runtimeUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  cells: { plot: "cell-id" },
  valueBindings: {
    "context.label": {
      variable: "context",
      cellId: "context-cell-id",
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
    runtimeConfig({ cells: { plot: 42 } }),
    runtimeConfig({
      valueBindings: {
        "context.label": {
          variable: "context",
          cellId: 42,
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

Deno.test("cell subscribers observe alias mapping changes", () => {
  commitRuntimeConfig(baseRuntimeConfig);
  const initial = getRuntimeCells();
  let calls = 0;
  const unsubscribe = subscribeRuntimeCells(() => calls++);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    view: "executive",
    supportUrl: "/proxy/app/_marimo-studio/views/executive",
    cells: { plot: "cell-id" },
  });

  assertStrictEquals(getRuntimeCells(), initial);
  assertEquals(calls, 0);

  commitRuntimeConfig({
    ...baseRuntimeConfig,
    cells: { plot: "next-cell-id" },
  });

  assertEquals(calls, 1);
  unsubscribe();
});
