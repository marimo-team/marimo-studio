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
      storageScope: "presentation-storage",
      capabilityToken: "presentation-capability",
      serverInstance: "server-instance",
      preserveSession: false,
    },
    urls: { transport: "https://hub.example/proxy/app/_marimo-studio/presentation/token/" },
  },
  rootUrl: "https://hub.example/proxy/app/",
  publicRootUrl: "https://hub.example/proxy/app/",
  documentRootUrl: "https://hub.example/proxy/app/",
  supportUrl: "https://hub.example/proxy/app/_marimo-studio/views/dashboard",
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

// Runtime configuration URLs resolve against the response that carried them.
const configUrl = "https://hub.example/proxy/app/_marimo-studio/views/dashboard/config";

test("runtime configuration accepts the browser contract", () => {
  const parsed = parseRuntimeConfig(runtimeConfig(), configUrl);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), baseRuntimeConfig);
  assert.equal(Object.getPrototypeOf(parsed.projectionTargets.cells), null);
  assert.equal(Object.getPrototypeOf(parsed.projectionTargets.variables), null);
  assert.equal(Object.getPrototypeOf(parsed.runtimeBindings.cellRefs), null);
  assert.equal(
    parseRuntimeConfig(runtimeConfig({ showCellLogs: false }), configUrl).showCellLogs,
    false,
  );
});

test("cell sites accept native names and configured aliases", () => {
  const targets = ["_summary", "résumé", "report-name"];
  const parsed = parseRuntimeConfig(
    runtimeConfig({
      sites: [
        {
          ...symbolicRuntimeFields.sites[0],
          targets: targets,
        },
      ],
    }),
    configUrl,
  );

  assert.deepEqual(parsed.sites[0]?.targets, targets);
});

test("document cell reads list the media types they accept", () => {
  const parsed = parseRuntimeConfig(
    runtimeConfig({ sites: [{ ...symbolicRuntimeFields.sites[0], accept: ["image/png"] }] }),
    configUrl,
  );

  assert.deepEqual(parsed.sites[0]?.accept, ["image/png"]);
});

test("runtime configuration resolves the Python delivery fixture beneath a proxy prefix", () => {
  const fixture = JSON.parse(
    readFileSync(new URL("../fixtures/runtime-config.json", import.meta.url), "utf8"),
  );
  // The proxy strips /s/f3a9/p/77c1 before the server sees the request.
  const parsed = parseRuntimeConfig(
    fixture,
    "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/views/dashboard/config",
  );

  assert.deepEqual(
    {
      rootUrl: parsed.rootUrl,
      publicRootUrl: parsed.publicRootUrl,
      documentRootUrl: parsed.documentRootUrl,
      supportUrl: parsed.supportUrl,
      runtimeUrls: { ...parsed.runtime.urls },
    },
    {
      rootUrl: "https://workbench.example/s/f3a9/p/77c1/",
      publicRootUrl: "https://workbench.example/s/f3a9/p/77c1/",
      documentRootUrl: "https://workbench.example/s/f3a9/p/77c1/",
      supportUrl: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/views/dashboard",
      runtimeUrls: {
        transport: "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/presentation/token/",
      },
    },
  );
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
    configUrl,
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
      sites: [
        {
          ...symbolicRuntimeFields.sites[0],
          targets: [],
        },
      ],
    }),
    runtimeConfig({
      sites: [{ ...symbolicRuntimeFields.sites[0], id: "SITE" }],
    }),
    runtimeConfig({
      sites: [{ ...symbolicRuntimeFields.sites[0], kind: "value", accept: ["image/png"] }],
    }),
    runtimeConfig({
      sites: [
        {
          ...symbolicRuntimeFields.sites[0],
          source: { path: ".ARTIFACTS/site.tsx", line: 1, column: 1 },
        },
      ],
    }),
    runtimeConfig({
      sites: [
        {
          ...symbolicRuntimeFields.sites[0],
          targets: [" plot "],
        },
      ],
    }),
    runtimeConfig({
      sites: [
        {
          ...symbolicRuntimeFields.sites[0],
          targets: ["_"],
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

  malformed.forEach((config) => assert.throws(() => parseRuntimeConfig(config, configUrl)));
});

// Mount URLs resolve against the document base that the server wrote.
const documentBase =
  "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/presentation/r.token/dashboard/_marimo-studio/artifacts/revision/";

test("mount configuration resolves its support URL against the document base", () => {
  const parsed = parseMountConfig(
    {
      supportUrl:
        "../../../../../../../_marimo-studio/presentation/r.token/_marimo-studio/views/dashboard",
      version: "test-version",
      revision: "presentation-revision",
      runtime: "server",
      runtimeExplicit: false,
      replay: false,
    },
    documentBase,
  );

  assert.equal(
    parsed.supportUrl,
    "https://workbench.example/s/f3a9/p/77c1/_marimo-studio/presentation/r.token/_marimo-studio/views/dashboard",
  );
});

test("mount configuration validates injected document data", () => {
  const mount = {
    supportUrl: "https://workbench.example/_marimo-studio/views/dashboard",
    version: "test-version",
    revision: "presentation-revision",
    runtime: "server",
    runtimeExplicit: false,
    replay: false,
  };
  const parse = (value: JsonValue) => parseMountConfig(value, documentBase);

  assert.deepEqual(parse(mount), mount);
  const owned = {
    ...mount,
    clientId: "client-123456789",
    lifecycleId: 7,
    runtimeSessionId: "s_abc123",
    renewalToken: "d.valid",
    replay: true,
  };
  assert.deepEqual(parse(owned), owned);
  assert.throws(() => parse({ ...mount, lifecycleId: 0 }));
  assert.throws(() => parse({ ...mount, runtimeSessionId: "forged" }));
  assert.equal(parse({ ...mount, clientId: "client-123456789" }).clientId, "client-123456789");
  assert.throws(() => parse({ ...mount, clientId: "short" }));
  assert.throws(() => parse({ ...mount, clientId: "client invalid!!" }));
  assert.throws(() => parse({ ...mount, lifecycleId: 7 }));
  assert.throws(() => parse({ ...mount, runtime: "wasm", runtimeSessionId: "s_abc123" }));
  assert.throws(() => parse({ ...mount, replay: true }));
  assert.throws(() => parse({ ...mount, renewalToken: "forged" }));
  assert.throws(() => parse({ ...mount, unexpected: true }));
});
