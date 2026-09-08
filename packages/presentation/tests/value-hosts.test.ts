import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import { parseValueReadResponse } from "@marimo-studio/protocol/value-read";
import assert from "node:assert/strict";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, test, vi } from "vite-plus/test";
import { z } from "zod";

import type { DecodedValue, DecodedValueReadResponse, MarimoValue } from "../src/values/codecs.ts";
import type { ValueReader } from "../src/values/reader.ts";

import { indexCells } from "../src/cells/index.ts";
import { startQuerySync } from "../src/document/query-sync.ts";
import {
  commitRuntimeConfig,
  loadRuntimeConfig,
  type RuntimeConfig,
} from "../src/runtime-config/index.ts";
import { RuntimeValueCell } from "../src/runtime/values/RuntimeValueCell.tsx";
import { RuntimeValues } from "../src/runtime/values/RuntimeValues.tsx";
import { createValueDecoder, decodeValueReadResponse } from "../src/values/codecs.ts";
import {
  applyValues,
  getValueHostProjections,
  isMarimoValueHost,
  type MarimoValueErrorDetail,
  type MarimoValueHost,
  type MarimoValueUpdatedDetail,
  markValueError,
  markValuePending,
  startValueHosts,
  stopValueHosts,
  subscribeValueHostProjections,
} from "../src/values/hosts.ts";
import { applyValueReadResponse } from "../src/values/response.ts";
import { ARROW_FINGERPRINT, arrowBytes } from "./arrow-fixture.ts";
import { runtimeCellFixture } from "./runtime-cell-fixture.ts";
import { projectionRequest, symbolicRuntimeFields } from "./runtime-fixtures.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined;

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

const baseConfig = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    data: {
      fileKey: "/workspace/notebook.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  showCellLogs: false,
  dev: false,
  mode: "run",
} satisfies RuntimeConfig;

const projectionRevisionFor = (selectors: readonly string[]): string => {
  const hash = selectors
    .join("\0")
    .split("")
    .reduce(
      (value, character) => Math.imul(value ^ character.charCodeAt(0), 16_777_619),
      2_166_136_261,
    );
  return (hash >>> 0).toString(16).padStart(8, "0").repeat(8);
};

const jsonValue = (value: JsonValue): Extract<DecodedValue, { codec: "json-v1" }> => ({
  codec: "json-v1",
  fingerprint: `sha256:${projectionRevisionFor([JSON.stringify(value)])}`,
  value,
});

const jsonValues = (values: Record<string, JsonValue>): Record<string, DecodedValue> =>
  Object.fromEntries(
    Object.entries(values).map(([selector, value]) => [selector, jsonValue(value)]),
  );

const configWithValues = (selectors: readonly string[], namespaceSite?: string): RuntimeConfig => ({
  ...baseConfig,
  projectionRevision: projectionRevisionFor(selectors),
  projectionTargets: {
    cells: {},
    variables: Object.fromEntries(
      selectors.map((selector) => [
        selector,
        {
          status: "ready",
          producer: `cell:v1:${selector}`,
          dependencyClosure: [`cell:v1:${selector}`],
        },
      ]),
    ),
  },
  mounts:
    namespaceSite === undefined
      ? selectors.map((selector) => ({
          id: `site:value:${selector}`,
          kind: "value" as const,
          source: { path: "src/App.tsx", line: 1, column: 1 },
          allowedTargets: [selector],
        }))
      : [
          {
            id: namespaceSite,
            kind: "value",
            source: { path: "src/App.tsx", line: 1, column: 1 },
            allowedTargets: null,
          },
        ],
  runtimeBindings: {
    cellRefs: Object.fromEntries(
      selectors.map((selector) => [`cell:v1:${selector}`, `${selector}-cell`]),
    ),
  },
});

const config = configWithValues(["nullable", "report"]);

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

const installConfig = async (next: RuntimeConfig = config): Promise<void> => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => Promise.resolve(Response.json(next));
  try {
    await loadRuntimeConfig();
  } finally {
    globalThis.fetch = originalFetch;
  }
};

afterEach(() => {
  act(() => root?.unmount());
  root = undefined;
  stopValueHosts();
  document.body.replaceChildren();
});

test("value hosts expose isolated snapshots through their DOM lifecycle", async () => {
  await installConfig();

  document.body.innerHTML = `
    <span id="first" mo-value="report" data-marimo-studio-site="site:value:report"></span>
    <span id="second" mo-value="report" data-marimo-studio-site="site:value:report"></span>
    <span id="nullable" mo-value="nullable" data-marimo-studio-site="site:value:nullable"></span>
  `;
  startValueHosts();

  const first = document.querySelector<MarimoValueHost>("#first")!;
  const second = document.querySelector<MarimoValueHost>("#second")!;
  const nullable = document.querySelector<MarimoValueHost>("#nullable")!;
  const updates: Array<{
    detail: MarimoValueUpdatedDetail;
    state: string | undefined;
    value: MarimoValue | undefined;
  }> = [];
  const errors: Array<{
    detail: MarimoValueErrorDetail;
    state: string | undefined;
    value: MarimoValue | undefined;
  }> = [];
  let bubbled: CustomEvent<MarimoValueUpdatedDetail> | undefined;
  let errorEvent: CustomEvent<MarimoValueErrorDetail> | undefined;
  first.addEventListener("marimo-value-updated", (event) => {
    updates.push({
      detail: structuredClone(event.detail),
      state: first.dataset.state,
      value: structuredClone(first.marimoValue),
    });
    z.object({ labels: z.array(z.string()) })
      .parse(event.detail.value)
      .labels.push("East");
  });
  first.addEventListener("marimo-value-error", (event) => {
    errorEvent = event;
    errors.push({
      detail: errorEvent.detail,
      state: first.dataset.state,
      value: first.marimoValue,
    });
  });
  document.addEventListener(
    "marimo-value-updated",
    (event) => {
      bubbled = event;
    },
    { once: true },
  );

  assert.equal(first.marimoValue, undefined);
  const property = Object.getOwnPropertyDescriptor(first, "marimoValue");
  assert.equal(property?.get instanceof Function, true);
  assert.equal(property?.set, undefined);
  const report = { labels: ["North", "South"], total: 42 };
  applyValues(jsonValues({ report }), config.projectionRevision);

  assert.deepEqual(updates, [
    {
      detail: { selector: "report", value: report },
      state: "ready",
      value: report,
    },
  ]);
  assert.equal(bubbled?.bubbles, true);
  assert.equal(bubbled?.composed, true);
  assert.equal(bubbled?.cancelable, false);

  assert.deepEqual(second.marimoValue, { labels: ["North", "South"], total: 42 });

  let nullUpdate: MarimoValueUpdatedDetail | undefined;
  nullable.addEventListener("marimo-value-updated", (event) => {
    nullUpdate = event.detail;
  });
  applyValues(jsonValues({ nullable: null }), config.projectionRevision);
  assert.equal(nullable.marimoValue, null);
  assert.deepEqual(nullUpdate, { selector: "nullable", value: null });

  markValuePending("report", config.projectionRevision);
  const retained = structuredClone(first.marimoValue);
  assert.equal(first.dataset.state, "stale");
  assert.equal(first.getAttribute("aria-busy"), "true");
  assert.deepEqual(first.marimoValue, retained);

  applyValues(
    jsonValues({ report: { labels: ["North", "South"], total: 42 } }),
    config.projectionRevision,
  );
  assert.equal(updates.length, 1);
  assert.deepEqual(first.marimoValue, report);
  assert.equal(first.dataset.state, "ready");

  const missingReport = {
    code: "missing-variable",
    message: "Variable 'report' is unavailable.",
    hint: "Restore the notebook variable.",
  };
  markValueError("report", missingReport, config.projectionRevision);
  markValueError("report", missingReport, config.projectionRevision);

  assert.equal(first.marimoValue, undefined);
  assert.equal(errorEvent?.bubbles, true);
  assert.equal(errorEvent?.composed, true);
  assert.deepEqual(errors, [
    {
      detail: {
        selector: "report",
        code: "missing-variable",
        message: "Variable 'report' is unavailable.",
        hint: "Restore the notebook variable.",
      },
      state: "error",
      value: undefined,
    },
  ]);
  assert.deepEqual(
    [
      first.dataset.marimoDiagnosticCode,
      first.dataset.marimoDiagnosticMessage,
      first.dataset.marimoDiagnosticHint,
    ],
    ["missing-variable", "Variable 'report' is unavailable.", "Restore the notebook variable."],
  );
});

test("value hosts share one decoded Arrow table without cloning it", async () => {
  const arrowConfig = configWithValues(["frame"]);
  await installConfig(arrowConfig);
  document.body.innerHTML = `
    <span id="first" mo-value="frame" data-marimo-studio-site="site:value:frame"></span>
    <span id="second" mo-value="frame" data-marimo-studio-site="site:value:frame"></span>
  `;
  startValueHosts();

  const bytes = arrowBytes();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(bytes.buffer);
  let response: DecodedValueReadResponse;
  try {
    const decode = createValueDecoder();
    const encoded = {
      values: {
        frame: {
          codec: "arrow-ipc-v1" as const,
          fingerprint: ARROW_FINGERPRINT,
          dataUrl: "/@file/frame.arrow",
          byteLength: bytes.byteLength,
        },
      },
      errors: {},
    };
    response = await decode(encoded, { activeSelectors: ["frame"] });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const first = document.querySelector<MarimoValueHost>("#first")!;
  const second = document.querySelector<MarimoValueHost>("#second")!;
  let firstUpdates = 0;
  first.addEventListener("marimo-value-updated", () => firstUpdates++);
  applyValueReadResponse(["frame"], response, arrowConfig.projectionRevision);
  const projected = response.values.frame;
  assert.equal(projected?.codec, "arrow-ipc-v1");
  if (projected?.codec !== "arrow-ipc-v1") {
    throw new Error("Expected an Arrow value");
  }

  assert.equal(first.marimoValue, second.marimoValue);
  assert.equal(first.marimoValue, projected.value);
  assert.equal(first.textContent, "2 rows × 2 columns");

  applyValueReadResponse(["frame"], response, arrowConfig.projectionRevision);
  assert.equal(first.marimoValue, projected.value);
  assert.equal(firstUpdates, 1);
});

test("adding one producer host does not reread existing producer groups", async () => {
  const valueConfig = configWithValues(["first", "second", "third"]);
  await installConfig(valueConfig);
  document.body.innerHTML = `
    <span mo-value="first" data-marimo-studio-site="site:value:first"></span>
    <span mo-value="second" data-marimo-studio-site="site:value:second"></span>
    <div id="root"></div>
  `;
  startValueHosts();
  root = createRoot(document.querySelector("#root")!);
  const requested: string[] = [];
  const readValues: ValueReader = async (request) => {
    const selectors = request.projections.map((projection) => projection.target);
    requested.push(...selectors);
    return {
      values: jsonValues(Object.fromEntries(selectors.map((selector) => [selector, selector]))),
      errors: {},
    };
  };
  const cells = indexCells(
    ["first", "second", "third"].map((selector) =>
      runtimeCellFixture({
        id: `${selector}-cell`,
        lastRunStartTimestamp: 1,
      }),
    ),
  );
  await act(async () => {
    root?.render(
      createElement(RuntimeValues, {
        cells,
        connectionState: "OPEN",
        readValues,
        runtimeReady: true,
      }),
    );
    await Promise.resolve();
  });
  await vi.waitFor(() => assert.deepEqual(requested.slice().sort(), ["first", "second"]));

  await act(async () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<span mo-value="third" data-marimo-studio-site="site:value:third"></span>',
    );
    await Promise.resolve();
  });
  await vi.waitFor(() => assert.equal(requested.filter((value) => value === "third").length, 1));

  assert.equal(requested.filter((value) => value === "first").length, 1);
  assert.equal(requested.filter((value) => value === "second").length, 1);
});

test("refreshes projected values when query state changes with the same producer", async () => {
  await installConfig(configWithValues(["report"]));
  document.body.innerHTML = `
    <span id="report" mo-value="report" data-marimo-studio-site="site:value:report"></span>
    <div id="root"></div>
  `;
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  const initialUrl = globalThis.location.href;
  globalThis.history.replaceState({}, "", "/?region=emea");
  startQuerySync();
  startValueHosts();
  root = createRoot(document.querySelector("#root")!);
  let value = "emea";
  const readValues: ValueReader = async () => ({
    values: jsonValues({ report: value }),
    errors: {},
  });
  try {
    await act(async () => {
      root?.render(
        createElement(RuntimeValues, {
          cells: indexCells([runtimeCellFixture({ id: "report-cell", lastRunStartTimestamp: 1 })]),
          connectionState: "OPEN",
          runtimeReady: true,
          readValues,
        }),
      );
    });
    await vi.waitFor(() => assert.equal(document.querySelector("#report")?.textContent, "emea"));

    await act(async () => {
      value = "apac";
      globalThis.history.replaceState({}, "", "/?region=apac");
    });
    await vi.waitFor(() => assert.equal(document.querySelector("#report")?.textContent, "apac"));
  } finally {
    act(() => root?.unmount());
    root = undefined;
    globalThis.history.pushState = pushState;
    globalThis.history.replaceState = replaceState;
    globalThis.history.replaceState({}, "", initialUrl);
  }
});

test("runtime value cells own producer identity across host changes", async () => {
  await installConfig();
  document.body.innerHTML = `
    <span id="report" mo-value="report" data-marimo-studio-site="site:value:report" data-runtime-cell-id="authored"></span>
    <span id="unknown" mo-value="unknown" data-marimo-studio-site="site:value:unknown" data-runtime-cell-id="authored"></span>
    <div id="root"></div>
  `;
  startValueHosts();

  const report = document.querySelector<HTMLElement>("#report")!;
  const unknown = document.querySelector<HTMLElement>("#unknown")!;
  assert.equal(report.dataset.runtimeCellId, "report-cell");
  assert.equal(report.dataset.marimoProducerRef, "cell:v1:report");
  assert.equal(unknown.dataset.runtimeCellId, undefined);

  root = createRoot(document.querySelector("#root")!);
  const renderCell = (cell = runtimeCellFixture({ id: "report-cell" })) => {
    root?.render(
      createElement(RuntimeValueCell, {
        projectionRevision: config.projectionRevision,
        selectors: ["report"],
        projections: [projectionRequest("report", "value")],
        cell,
        connectionState: "CLOSED",
        runtimeReady: true,
        readValues: async () => ({ values: {}, errors: {} }),
      }),
    );
  };

  act(() => renderCell());
  assert.equal(report.dataset.runtimeCellId, "report-cell");

  const late = document.createElement("span");
  late.setAttribute("mo-value", "report");
  late.dataset.marimoStudioSite = "site:value:report";
  document.body.append(late);
  await settleMutations();
  assert.equal(late.dataset.runtimeCellId, "report-cell");

  act(() => renderCell(runtimeCellFixture({ id: "next-cell" })));
  assert.equal(report.dataset.runtimeCellId, "next-cell");
  assert.equal(late.dataset.runtimeCellId, "next-cell");

  act(() => {
    root?.render(
      createElement(RuntimeValueCell, {
        projectionRevision: config.projectionRevision,
        selectors: ["report"],
        projections: [projectionRequest("report", "value")],
        cell: undefined,
        connectionState: "CLOSED",
        runtimeReady: false,
        readValues: async () => ({ values: {}, errors: {} }),
      }),
    );
  });
  assert.equal(report.dataset.runtimeCellId, undefined);
  assert.equal(late.dataset.runtimeCellId, undefined);
});

test("value reads keep their projection while advancing the next wire revision", async () => {
  const valueConfig = configWithValues(["report"]);
  await installConfig(valueConfig);
  document.body.innerHTML = `
    <span mo-value="report" data-marimo-studio-site="site:value:report"></span>
    <div id="root"></div>
  `;
  startValueHosts();
  root = createRoot(document.querySelector("#root")!);
  const selectors = ["report"];
  const projections = [projectionRequest("report", "value")];
  const revisions: string[] = [];
  let aborts = 0;
  const readValues = async (request: { revision: string }, signal?: AbortSignal) => {
    revisions.push(request.revision);
    signal?.addEventListener("abort", () => aborts++, { once: true });
    return { values: jsonValues({ report: revisions.length }), errors: {} };
  };
  const render = async (requestRevision: string, version: number) => {
    await act(async () => {
      commitRuntimeConfig({ ...valueConfig, revision: requestRevision });
      root?.render(
        createElement(RuntimeValueCell, {
          projectionRevision: valueConfig.projectionRevision,
          selectors,
          projections,
          cell: runtimeCellFixture({
            id: "report-cell",
            lastRunStartTimestamp: version,
          }),
          connectionState: "OPEN",
          runtimeReady: true,
          readValues,
        }),
      );
      await Promise.resolve();
    });
  };

  await render("presentation-a", 1);
  await render("presentation-b", 1);
  assert.deepEqual(revisions, ["presentation-a"]);
  assert.equal(aborts, 0);

  await render("presentation-b", 2);
  assert.deepEqual(revisions, ["presentation-a", "presentation-b"]);
});

test("a replaced projection rejects a late value response that ignored abort", async () => {
  const previousConfig = {
    ...configWithValues(["report"]),
    revision: "presentation-revision",
    projectionRevision: "a".repeat(64),
  };
  const currentConfig = {
    ...previousConfig,
    revision: "presentation-b",
    projectionRevision: "b".repeat(64),
  };
  await installConfig(previousConfig);
  document.body.innerHTML = `
    <span mo-value="report" data-marimo-studio-site="site:value:report"></span>
    <div id="root"></div>
  `;
  startValueHosts();
  root = createRoot(document.querySelector("#root")!);
  const host = document.querySelector<MarimoValueHost>("[mo-value]")!;
  const selectors = ["report"];
  const projections = [projectionRequest("report", "value")];
  let resolvePrevious!: (response: DecodedValueReadResponse) => void;
  const previousResponse = new Promise<DecodedValueReadResponse>((resolve) => {
    resolvePrevious = resolve;
  });
  let previousSignal: AbortSignal | undefined;
  const previousReader: ValueReader = (_request, signal) => {
    previousSignal = signal;
    return previousResponse;
  };
  const currentReader: ValueReader = async () => ({
    values: jsonValues({ report: "current" }),
    errors: {},
  });
  const render = async (nextConfig: RuntimeConfig, version: number, readValues: ValueReader) => {
    await act(async () => {
      commitRuntimeConfig(nextConfig);
      root?.render(
        createElement(RuntimeValueCell, {
          projectionRevision: nextConfig.projectionRevision,
          selectors,
          projections,
          cell: runtimeCellFixture({
            id: "report-cell",
            lastRunStartTimestamp: version,
          }),
          connectionState: "OPEN",
          runtimeReady: true,
          readValues,
        }),
      );
      await Promise.resolve();
    });
  };

  await render(previousConfig, 1, previousReader);
  assert.ok(previousSignal);
  await render(currentConfig, 2, currentReader);
  assert.equal(previousSignal.aborted, true);
  assert.equal(host.marimoValue, "current");

  await act(async () => {
    resolvePrevious({ values: jsonValues({ report: "stale" }), errors: {} });
    await previousResponse;
    await Promise.resolve();
  });

  assert.equal(host.marimoValue, "current");
  assert.equal(host.textContent, "current");
});

test("value host ownership follows authored DOM reparenting", async () => {
  await installConfig();
  document.body.innerHTML = `
    <div id="first"><span mo-value="report" data-marimo-studio-site="site:value:report"></span></div>
    <div id="second"></div>
  `;
  startValueHosts();
  const host = document.querySelector<MarimoValueHost>("[mo-value]")!;
  applyValues(jsonValues({ report: { total: 42 } }), config.projectionRevision);
  let projectionChanges = 0;
  const unsubscribe = subscribeValueHostProjections(() => projectionChanges++);
  let updates = 0;
  host.addEventListener("marimo-value-updated", () => updates++);

  document.querySelector("#second")!.append(host);
  await settleMutations();

  assert.deepEqual(host.marimoValue, { total: 42 });
  assert.equal(host.dataset.state, "ready");
  assert.equal(projectionChanges, 0);
  assert.equal(updates, 0);

  const nativeOutput = document.createElement("div");
  nativeOutput.setAttribute("data-marimo-cell-output", "");
  const shadow = nativeOutput.attachShadow({ mode: "open" });
  document.body.append(nativeOutput);
  shadow.append(host);
  await settleMutations();

  assert.deepEqual(getValueHostProjections(), []);
  assert.equal(isMarimoValueHost(host), false);
  assert.equal(host.dataset.state, undefined);
  assert.equal(host.textContent, "");

  document.querySelector("#second")!.append(host);
  await settleMutations();

  assert.equal(isMarimoValueHost(host), true);
  assert.equal(host.dataset.state, "connecting");
  assert.equal(getValueHostProjections().length, 1);
  applyValues(jsonValues({ report: { total: 43 } }), config.projectionRevision);
  assert.deepEqual(host.marimoValue, { total: 43 });
  assert.equal(updates, 1);
  unsubscribe();
});

test("a value update listener can retarget a newly connected host", async () => {
  const dynamic = configWithValues(["alpha", "beta"], "site:dynamic-value");
  await installConfig(dynamic);
  document.body.innerHTML = `
    <span mo-value="alpha" data-marimo-studio-site="site:dynamic-value"></span>
    <span id="beta" mo-value="beta" data-marimo-studio-site="site:dynamic-value"></span>
  `;
  startValueHosts();
  applyValues(jsonValues({ alpha: 1, beta: 2 }), dynamic.projectionRevision);
  await settleMutations();
  const host = document.createElement("span");
  host.setAttribute("mo-value", "alpha");
  host.addEventListener("marimo-value-updated", (event) => {
    if (event.detail.selector === "alpha") {
      host.setAttribute("mo-value", "beta");
    }
  });

  document.body.append(host);
  host.setAttribute("data-marimo-studio-site", "site:dynamic-value");
  await settleMutations();
  document.querySelector("#beta")!.remove();
  await settleMutations();
  applyValues(jsonValues({ beta: 22 }), dynamic.projectionRevision);

  assert.ok(isMarimoValueHost(host));
  assert.equal(host.marimoValue, 22);
  assert.equal(host.textContent, "22");
  assert.equal(host.dataset.runtimeCellId, "beta-cell");
});

test("value host observation leaves other projection hosts intact", async () => {
  await installConfig();
  document.body.innerHTML = `
    <marimo-output data-marimo-studio-site="site:output:first">
      <div data-marimo-cell-output>Rendered output</div>
    </marimo-output>
  `;
  startValueHosts();
  const output = document.querySelector<HTMLElement>("marimo-output")!;

  output.dataset.marimoStudioSite = "site:output:second";
  await settleMutations();

  assert.equal(output.textContent?.trim(), "Rendered output");
  assert.equal(isMarimoValueHost(output), false);
});

test("dynamic value hosts follow their active selector", async () => {
  const dynamicSite = "site:value:dynamic";
  const dynamicConfig = configWithValues(["dynamic", "copy", "mirror"], dynamicSite);
  await installConfig(dynamicConfig);
  document.body.innerHTML = `<span id="source" mo-value="dynamic" data-marimo-studio-site="${dynamicSite}"></span>`;
  startValueHosts();

  const source = document.querySelector<MarimoValueHost>("#source")!;
  const report = { labels: ["North", "South"], total: 42 };
  const updates: MarimoValueUpdatedDetail[] = [];
  let errors = 0;
  source.addEventListener("marimo-value-updated", (event) => {
    updates.push(structuredClone(event.detail));
  });
  source.addEventListener("marimo-value-error", () => errors++);
  applyValues(jsonValues({ dynamic: report }), dynamicConfig.projectionRevision);

  const late = document.createElement("span");
  late.setAttribute("mo-value", "dynamic");
  late.dataset.marimoStudioSite = dynamicSite;
  document.body.append(late);
  await settleMutations();
  assert.ok(isMarimoValueHost(late));
  assert.deepEqual(late.marimoValue, report);

  source.setAttribute("mo-value", "copy");
  await settleMutations();
  assert.equal(source.marimoValue, undefined);
  assert.equal(source.textContent, "");

  applyValues(jsonValues({ copy: report }), dynamicConfig.projectionRevision);
  assert.deepEqual(source.marimoValue, report);
  assert.deepEqual(updates.at(-1), { selector: "copy", value: report });

  applyValues(jsonValues({ mirror: report }), dynamicConfig.projectionRevision);
  const updatesBeforeBatch = updates.length;
  source.setAttribute("mo-value", "dynamic");
  source.setAttribute("mo-value", "mirror");
  await settleMutations();
  assert.equal(updates.length, updatesBeforeBatch);
  assert.equal(source.marimoValue, undefined);
  assert.equal(source.dataset.state, "connecting");

  applyValues(jsonValues({ mirror: report }), dynamicConfig.projectionRevision);
  assert.equal(updates.length, updatesBeforeBatch + 1);
  assert.deepEqual(updates.at(-1), { selector: "mirror", value: report });

  source.removeAttribute("mo-value");
  await settleMutations();
  const updatesAfterRemoval = updates.length;
  applyValues(jsonValues({ mirror: "new value" }), dynamicConfig.projectionRevision);
  assert.equal(errors, 0);
  assert.equal(updates.length, updatesAfterRemoval);
  assert.equal(source.textContent, "");
  assert.equal(source.dataset.state, undefined);

  source.setAttribute("mo-value", "mirror");
  await settleMutations();
  assert.equal(source.marimoValue, undefined);
  assert.equal(source.dataset.state, "connecting");

  stopValueHosts();
  const dormant = document.createElement("span");
  dormant.setAttribute("mo-value", "dynamic");
  dormant.dataset.marimoStudioSite = dynamicSite;
  document.body.append(dormant);
  await settleMutations();
  assert.equal(dormant.dataset.state, undefined);
});

test("changing a value source site reconnects the same projection instance", async () => {
  const next = configWithValues(["report"]);
  await installConfig({
    ...next,
    mounts: [
      {
        id: "site:value:first",
        kind: "value",
        source: { path: "src/App.tsx", line: 1, column: 1 },
        allowedTargets: ["report"],
      },
      {
        id: "site:value:second",
        kind: "value",
        source: { path: "src/App.tsx", line: 2, column: 1 },
        allowedTargets: ["report"],
      },
    ],
  });
  document.body.innerHTML = `
    <span mo-value="report" data-marimo-studio-site="site:value:first"></span>
  `;
  startValueHosts();
  const host = document.querySelector<MarimoValueHost>("span")!;
  const initial = getValueHostProjections()[0]!.request;

  host.dataset.marimoStudioSite = "site:value:second";
  await settleMutations();

  const current = getValueHostProjections()[0]!.request;
  assert.equal(current.siteId, "site:value:second");
  assert.equal(current.instanceId, initial.instanceId);
  assert.equal(host.dataset.state, "connecting");
});

test("an empty dynamic value target recovers through the same host instance", async () => {
  const dynamicSite = "site:value:dynamic-recovery";
  const dynamicConfig = configWithValues(["metric"], dynamicSite);
  await installConfig(dynamicConfig);
  document.body.innerHTML = `<strong mo-value="" data-marimo-studio-site="${dynamicSite}"></strong>`;
  startValueHosts();

  const host = document.querySelector<MarimoValueHost>("strong")!;
  const instanceId = host.dataset.marimoStudioInstance;
  assert.equal(host.dataset.state, "error");
  assert.equal(host.dataset.marimoDiagnosticCode, "projection-target-empty");
  assert.equal(host.dataset.marimoProducerRef, undefined);

  host.setAttribute("mo-value", "metric");
  await settleMutations();
  assert.equal(host.dataset.marimoStudioInstance, instanceId);
  assert.equal(host.dataset.state, "connecting");
  assert.equal(host.dataset.marimoDiagnosticCode, undefined);
  assert.equal(host.dataset.marimoProducerRef, "cell:v1:metric");

  applyValues(jsonValues({ metric: 42 }), dynamicConfig.projectionRevision);
  assert.equal(host.dataset.state, "ready");
  assert.equal(host.textContent, "42");
});

test("a projection replacement reconciles hosts against incoming symbols", async () => {
  const previousConfig = configWithValues(["previous"]);
  await installConfig(previousConfig);
  document.body.innerHTML = `<span id="previous" mo-value="previous" data-marimo-studio-site="site:value:previous"></span>`;
  startValueHosts();

  const previous = document.querySelector<MarimoValueHost>("#previous")!;
  let outgoingErrors = 0;
  previous.addEventListener("marimo-value-error", () => outgoingErrors++);
  applyValues(jsonValues({ previous: "ready" }), previousConfig.projectionRevision);

  const incomingConfig = {
    ...configWithValues(["incoming"]),
    revision: "incoming-revision",
    projectionRevision: "b".repeat(64),
  };
  commitRuntimeConfig(incomingConfig);
  assert.equal(previous.marimoValue, undefined);
  assert.equal(previous.dataset.state, "connecting");
  document.body.innerHTML = `<span id="incoming" mo-value="incoming" data-marimo-studio-site="site:value:incoming"></span>`;
  await settleMutations();

  const incoming = document.querySelector<MarimoValueHost>("#incoming")!;
  let update: MarimoValueUpdatedDetail | undefined;
  incoming.addEventListener("marimo-value-updated", (event) => {
    update = event.detail;
  });
  applyValues(jsonValues({ previous: "stale" }), previousConfig.projectionRevision);
  applyValues(jsonValues({ incoming: "ready" }), incomingConfig.projectionRevision);
  assert.equal(outgoingErrors, 0);
  assert.deepEqual(update, { selector: "incoming", value: "ready" });
});

test("response-wide read failures retain their structured error", async () => {
  const wideConfig = configWithValues(["wide"]);
  await installConfig(wideConfig);
  document.body.innerHTML = `<span id="wide" mo-value="wide" data-marimo-studio-site="site:value:wide"></span>`;
  startValueHosts();

  const wide = document.querySelector<MarimoValueHost>("#wide")!;
  let failure: MarimoValueErrorDetail | undefined;
  wide.addEventListener("marimo-value-error", (event) => {
    failure = event.detail;
  });
  applyValueReadResponse(
    ["wide"],
    {
      values: {},
      errors: {
        "*": {
          code: "response-too-large",
          message: "The value response exceeds the aggregate byte limit.",
        },
      },
    },
    wideConfig.projectionRevision,
  );

  assert.deepEqual(failure, {
    selector: "wide",
    code: "response-too-large",
    message: "The value response exceeds the aggregate byte limit.",
  });
});

test("value hosts resolve prototype-named notebook symbols from own response records", async () => {
  const selectors = ["__proto__", "constructor"];
  const siteId = "site:value:prototype-names";
  const prototypeConfig = configWithValues(selectors, siteId);
  await installConfig(prototypeConfig);
  document.body.innerHTML = selectors
    .map(
      (selector, index) =>
        `<span id="prototype-${index}" mo-value="${selector}" data-marimo-studio-site="${siteId}"></span>`,
    )
    .join("");
  startValueHosts();

  const response = await decodeValueReadResponse(
    parseValueReadResponse({
      values: Object.fromEntries(
        selectors.map((selector, index) => [selector, jsonValue(`value-${index}`)]),
      ),
      errors: {},
    }),
  );
  applyValueReadResponse(selectors, response, prototypeConfig.projectionRevision);

  selectors.forEach((_, index) => {
    const host = document.querySelector<MarimoValueHost>(`#prototype-${index}`)!;
    assert.equal(host.dataset.state, "ready");
    assert.equal(host.marimoValue, `value-${index}`);
  });
});

test("value hosts treat inherited response properties as absent", async () => {
  const siteId = "site:value:prototype-absence";
  const prototypeConfig = configWithValues(["constructor"], siteId);
  await installConfig(prototypeConfig);
  document.body.innerHTML = `<span mo-value="constructor" data-marimo-studio-site="${siteId}"></span>`;
  startValueHosts();

  const host = document.querySelector<MarimoValueHost>("span")!;
  applyValueReadResponse(
    ["constructor"],
    { values: {}, errors: {} },
    prototypeConfig.projectionRevision,
  );

  assert.equal(host.dataset.state, "error");
  assert.equal(host.dataset.marimoDiagnosticCode, "missing-value-response");
});
