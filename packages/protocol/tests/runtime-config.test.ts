import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseMountConfig, parseRuntimeConfig, type RuntimeConfig } from "../src/runtime-config.ts";

const baseRuntimeConfig = {
  schema: 1,
  revision: "presentation-revision",
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
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  serverToken: "server-token",
  dev: true,
  mode: "edit",
  preserveSession: false,
} satisfies RuntimeConfig;

const runtimeConfig = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  ...baseRuntimeConfig,
  ...overrides,
});

test("runtime configuration accepts the browser contract", () => {
  assert.deepEqual(parseRuntimeConfig(runtimeConfig()), baseRuntimeConfig);
  assert.deepEqual(parseRuntimeConfig(runtimeConfig({ ignored: true })), baseRuntimeConfig);
});

test("runtime configuration accepts repairable projection diagnostics", () => {
  const diagnostic = {
    code: "cell-not-found",
    severity: "error",
    message: "Cell 'summary' is unavailable.",
    hint: "Restore the cell or update the view.",
    view: "dashboard",
    projection: "cell",
    target: "summary",
    source: {
      path: "/workspace/__marimo__/studio/notebook/dashboard/index.html",
      line: 18,
      column: 7,
    },
  };

  assert.deepEqual(parseRuntimeConfig(runtimeConfig({ diagnostics: [diagnostic] })).diagnostics, [
    diagnostic,
  ]);
});

test("runtime configuration rejects malformed server contracts", () => {
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
    runtimeConfig({ revision: 42 }),
    runtimeConfig({ view: 42 }),
    runtimeConfig({ view: "missing" }),
    runtimeConfig({ views: ["dashboard", 42] }),
    runtimeConfig({
      diagnostics: [
        {
          code: "cell-not-found",
          severity: "error",
          message: "Missing cell",
          hint: "Restore it",
          view: "dashboard",
          projection: "cell",
          target: "summary",
          source: { path: "index.html", line: "18", column: 7 },
        },
      ],
    }),
    missingPolicy,
    runtimeConfig({ preserveSession: "yes" }),
  ];

  malformed.forEach((config) => assert.throws(() => parseRuntimeConfig(config)));
});

test("mount configuration validates injected document data", () => {
  const mount = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "0.23.16",
    revision: "presentation-revision",
  };

  assert.deepEqual(parseMountConfig(mount), mount);
  assert.throws(() => parseMountConfig({ ...mount, revision: 42 }));
});
