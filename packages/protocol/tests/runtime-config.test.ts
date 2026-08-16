import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  parseMountConfig,
  parseRuntimeConfig,
  type JsonValue,
  type RuntimeConfig,
} from "../src/runtime-config.ts";

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
} as const;

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
    controls: {
      cells: {
        "cell:v1:semantic": "MJUe",
      },
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
  outputBindings: {
    "context.table": {
      variable: "context",
      cell: { kind: "id", value: "context-cell-id" },
    },
  },
  diagnostics: [diagnostic],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: true,
  mode: "edit",
} satisfies RuntimeConfig;

type RuntimeConfigOverrides = Readonly<Record<string, JsonValue>>;

const runtimeConfig = (overrides: RuntimeConfigOverrides = {}) => ({
  ...baseRuntimeConfig,
  ...overrides,
});

test("runtime configuration accepts the browser contract", () => {
  assert.deepEqual(parseRuntimeConfig(runtimeConfig()), baseRuntimeConfig);
  assert.deepEqual(parseRuntimeConfig(runtimeConfig({ ignored: true })), baseRuntimeConfig);
  assert.equal(parseRuntimeConfig(runtimeConfig({ showCellLogs: false })).showCellLogs, false);
  const { showCellLogs: _, ...legacyRuntimeConfig } = runtimeConfig();
  assert.equal(parseRuntimeConfig(legacyRuntimeConfig).showCellLogs, true);
});

test("runtime configuration rejects malformed contracts", () => {
  const malformed = [
    runtimeConfig({ cellBindings: { plot: { kind: "index", value: "plot" } } }),
    runtimeConfig({ view: "missing" }),
    runtimeConfig({ runtime: { ...baseRuntimeConfig.runtime, id: "WASM" } }),
    runtimeConfig({
      runtime: { ...baseRuntimeConfig.runtime, id: "custom", available: ["server"] },
    }),
  ];

  malformed.forEach((config) => assert.throws(() => parseRuntimeConfig(config)));
});

test("mount configuration validates injected document data", () => {
  const mount = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "test-version",
    revision: "presentation-revision",
    runtime: "server",
  };

  assert.deepEqual(parseMountConfig(mount), mount);
  assert.throws(() => parseMountConfig({ ...mount, revision: 42 }));
  assert.throws(() => parseMountConfig({ ...mount, runtime: "WebAssembly" }));
});
