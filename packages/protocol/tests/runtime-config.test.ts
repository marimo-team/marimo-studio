import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "vite-plus/test";

import {
  parseMountConfig,
  parseRuntimeConfig,
  type JsonValue,
  type RuntimeConfig,
} from "../src/runtime-config.ts";
import { symbolicRuntimeFields } from "./fixtures.ts";

const diagnostic = {
  code: "cell-not-found",
  severity: "error",
  message: "Cell 'summary' is unavailable.",
  hint: "Restore the cell or update the view.",
  view: "dashboard",
  projection: "cell",
  target: "summary",
  source: {
    path: "src/index.html",
    line: 18,
    column: 7,
  },
} as const;

const baseRuntimeConfig = {
  schema: 1,
  revision: "presentation-revision",
  projectionRevision: "a".repeat(64),
  view: "dashboard",
  views: ["dashboard", "executive"],
  runtime: {
    id: "server",
    instance: "server-instance",
    data: {
      fileKey: "/workspace/notebook.py",
      capabilityToken: "presentation-capability",
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
  const parsed = parseRuntimeConfig(runtimeConfig());
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), baseRuntimeConfig);
  assert.equal(Object.getPrototypeOf(parsed.projectionTargets.cells), null);
  assert.equal(Object.getPrototypeOf(parsed.projectionTargets.variables), null);
  assert.equal(Object.getPrototypeOf(parsed.runtimeBindings.cellRefs), null);
  assert.equal(parseRuntimeConfig(runtimeConfig({ showCellLogs: false })).showCellLogs, false);
});

test("cell mounts accept native names and configured aliases", () => {
  const targets = ["_summary", "résumé", "report-name"];
  const parsed = parseRuntimeConfig(
    runtimeConfig({
      mounts: [
        {
          ...symbolicRuntimeFields.mounts[0],
          allowedTargets: targets,
        },
      ],
    }),
  );

  assert.deepEqual(parsed.mounts[0]?.allowedTargets, targets);
});

test("runtime configuration accepts the Python delivery fixture", () => {
  const fixture = JSON.parse(
    readFileSync(new URL("../fixtures/runtime-config.json", import.meta.url), "utf8"),
  );

  assert.deepEqual(JSON.parse(JSON.stringify(parseRuntimeConfig(fixture))), fixture);
});

test("runtime configuration preserves prototype-named projection targets", () => {
  const names = ["__proto__", "constructor"];
  const refs = names.map((_, index) => `cell:v1:prototype-${index}`);
  const parsed = parseRuntimeConfig(
    runtimeConfig({
      projectionTargets: {
        cells: Object.fromEntries(
          names.map((name, index) => [
            name,
            {
              status: "ready",
              producer: refs[index],
              dependencyClosure: [refs[index]],
            },
          ]),
        ),
        variables: Object.fromEntries(
          names.map((name, index) => [
            name,
            {
              status: "ready",
              producer: refs[index],
              dependencyClosure: [refs[index]],
            },
          ]),
        ),
      },
      runtimeBindings: {
        cellRefs: Object.fromEntries(refs.map((ref, index) => [ref, `runtime-${index}`])),
      },
    }),
  );

  names.forEach((name, index) => {
    assert.equal(Object.hasOwn(parsed.projectionTargets.cells, name), true);
    assert.deepEqual(parsed.projectionTargets.cells[name], {
      status: "ready",
      producer: refs[index],
      dependencyClosure: [refs[index]],
    });
    assert.equal(Object.hasOwn(parsed.projectionTargets.variables, name), true);
  });
});

test("runtime configuration rejects malformed contracts", () => {
  const malformed: JsonValue[] = [
    runtimeConfig({ projectionRevision: "not-a-sha256-digest" }),
    runtimeConfig({
      mounts: [
        {
          ...symbolicRuntimeFields.mounts[0],
          allowedTargets: [],
        },
      ],
    }),
    runtimeConfig({
      mounts: [{ ...symbolicRuntimeFields.mounts[0], id: "SITE" }],
    }),
    runtimeConfig({
      mounts: [
        {
          ...symbolicRuntimeFields.mounts[0],
          source: { path: ".ARTIFACTS/site.tsx", line: 1, column: 1 },
        },
      ],
    }),
    runtimeConfig({
      mounts: [
        {
          ...symbolicRuntimeFields.mounts[0],
          allowedTargets: [" plot "],
        },
      ],
    }),
    runtimeConfig({
      mounts: [
        {
          ...symbolicRuntimeFields.mounts[0],
          allowedTargets: ["_"],
        },
      ],
    }),
    runtimeConfig({ view: "missing" }),
    runtimeConfig({ runtime: { ...baseRuntimeConfig.runtime, id: "WASM" } }),
    runtimeConfig({ ignored: true }),
    runtimeConfig({
      runtime: { ...baseRuntimeConfig.runtime, unexpected: true },
    }),
    runtimeConfig({
      diagnostics: [{ ...diagnostic, unexpected: true }],
    }),
    runtimeConfig({
      diagnostics: [{ ...diagnostic, source: { ...diagnostic.source, unexpected: true } }],
    }),
  ];

  const { showCellLogs: _, ...withoutLogPreference } = runtimeConfig();
  malformed.push(withoutLogPreference);

  malformed.forEach((config) => assert.throws(() => parseRuntimeConfig(config)));
});

test("mount configuration validates injected document data", () => {
  const mount = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "test-version",
    revision: "presentation-revision",
    runtime: "server",
    runtimeExplicit: false,
    replay: false,
  };

  assert.deepEqual(parseMountConfig(mount), mount);
  const owned = {
    ...mount,
    clientId: "client-123456789",
    lifecycleId: 7,
    runtimeSessionId: "s_abc123",
    renewalToken: "d.valid",
    replay: true,
  };
  assert.deepEqual(parseMountConfig(owned), owned);
  assert.throws(() => parseMountConfig({ ...mount, lifecycleId: 0 }));
  assert.throws(() => parseMountConfig({ ...mount, runtimeSessionId: "forged" }));
  assert.equal(
    parseMountConfig({ ...mount, clientId: "client-123456789" }).clientId,
    "client-123456789",
  );
  assert.throws(() => parseMountConfig({ ...mount, clientId: "short" }));
  assert.throws(() => parseMountConfig({ ...mount, clientId: "client invalid!!" }));
  assert.throws(() => parseMountConfig({ ...mount, lifecycleId: 7 }));
  assert.throws(() =>
    parseMountConfig({ ...mount, runtime: "wasm", runtimeSessionId: "s_abc123" }),
  );
  assert.throws(() => parseMountConfig({ ...mount, replay: true }));
  assert.throws(() => parseMountConfig({ ...mount, renewalToken: "forged" }));
  assert.throws(() => parseMountConfig({ ...mount, unexpected: true }));
});
