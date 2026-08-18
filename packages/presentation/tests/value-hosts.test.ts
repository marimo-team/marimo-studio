import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";
import { z } from "zod";

import {
  commitRuntimeConfig,
  loadRuntimeConfig,
  type RuntimeConfig,
} from "../src/runtime-config/index.ts";
import {
  applyValues,
  isMarimoValueHost,
  type MarimoValueErrorDetail,
  type MarimoValueHost,
  type MarimoValueUpdatedDetail,
  markValueError,
  markValuePending,
  startValueBindings,
  stopValueBindings,
} from "../src/values/hosts.ts";
import { applyValueReadResponse } from "../src/values/response.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
};

const config = {
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server"],
    data: {
      fileKey: "/workspace/notebook.py",
      serverToken: "server-token",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {
    nullable: {
      variable: "nullable",
      cell: { kind: "id", value: "nullable-cell" },
    },
    report: {
      variable: "report",
      cell: { kind: "id", value: "report-cell" },
    },
  },
  outputBindings: {},
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  showCellLogs: false,
  dev: false,
  mode: "run",
} satisfies RuntimeConfig;

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

const configWithBindings = (...selectors: string[]): RuntimeConfig => ({
  ...config,
  valueBindings: Object.fromEntries(
    selectors.map((selector) => [
      selector,
      {
        variable: selector,
        cell: { kind: "id" as const, value: `${selector}-cell` },
      },
    ]),
  ),
});

afterEach(() => {
  stopValueBindings();
  document.body.replaceChildren();
});

test("value hosts expose isolated snapshots through their DOM lifecycle", async () => {
  await installConfig();

  document.body.innerHTML = `
    <span id="first" mo-value="report"></span>
    <span id="second" mo-value="report"></span>
    <span id="nullable" mo-value="nullable"></span>
  `;
  startValueBindings();

  const first = document.querySelector<MarimoValueHost>("#first")!;
  const second = document.querySelector<MarimoValueHost>("#second")!;
  const nullable = document.querySelector<MarimoValueHost>("#nullable")!;
  const updates: Array<{
    detail: MarimoValueUpdatedDetail;
    state: string | undefined;
    value: JsonValue | undefined;
  }> = [];
  const errors: Array<{
    detail: MarimoValueErrorDetail;
    state: string | undefined;
    value: JsonValue | undefined;
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
  applyValues({ report });

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
  applyValues({ nullable: null });
  assert.equal(nullable.marimoValue, null);
  assert.deepEqual(nullUpdate, { selector: "nullable", value: null });

  markValuePending("report");
  const retained = structuredClone(first.marimoValue);
  assert.equal(first.dataset.state, "stale");
  assert.equal(first.getAttribute("aria-busy"), "true");
  assert.deepEqual(first.marimoValue, retained);

  applyValues({ report: { labels: ["North", "South"], total: 42 } });
  assert.equal(updates.length, 1);
  assert.deepEqual(first.marimoValue, report);
  assert.equal(first.dataset.state, "ready");

  const missingReport = {
    code: "missing-variable",
    message: "Variable 'report' is unavailable.",
    hint: "Restore the notebook variable.",
  };
  markValueError("report", missingReport);
  markValueError("report", missingReport);

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

test("dynamic value hosts follow their active selector", async () => {
  await installConfig(configWithBindings("dynamic", "copy", "mirror"));
  document.body.innerHTML = `<span id="source" mo-value="dynamic"></span>`;
  startValueBindings();

  const source = document.querySelector<MarimoValueHost>("#source")!;
  const report = { labels: ["North", "South"], total: 42 };
  const updates: MarimoValueUpdatedDetail[] = [];
  let errors = 0;
  source.addEventListener("marimo-value-updated", (event) => {
    updates.push(structuredClone(event.detail));
  });
  source.addEventListener("marimo-value-error", () => errors++);
  applyValues({ dynamic: report });

  const late = document.createElement("span");
  late.setAttribute("mo-value", "dynamic");
  document.body.append(late);
  await settleMutations();
  assert.ok(isMarimoValueHost(late));
  assert.deepEqual(late.marimoValue, report);

  source.setAttribute("mo-value", "copy");
  await settleMutations();
  assert.equal(source.marimoValue, undefined);
  assert.equal(source.textContent, "");

  applyValues({ copy: report });
  assert.deepEqual(source.marimoValue, report);
  assert.deepEqual(updates.at(-1), { selector: "copy", value: report });

  applyValues({ mirror: report });
  const updatesBeforeBatch = updates.length;
  source.setAttribute("mo-value", "dynamic");
  source.setAttribute("mo-value", "mirror");
  await settleMutations();
  assert.equal(updates.length, updatesBeforeBatch + 1);
  assert.deepEqual(updates.at(-1), { selector: "mirror", value: report });

  source.removeAttribute("mo-value");
  await settleMutations();
  const updatesAfterRemoval = updates.length;
  applyValues({ mirror: "new value" });
  assert.equal(errors, 0);
  assert.equal(updates.length, updatesAfterRemoval);
  assert.equal(source.textContent, "");
  assert.equal(source.dataset.state, undefined);

  stopValueBindings();
  const dormant = document.createElement("span");
  dormant.setAttribute("mo-value", "dynamic");
  document.body.append(dormant);
  await settleMutations();
  assert.equal(dormant.dataset.state, undefined);
});

test("a shell replacement reconciles hosts against the incoming bindings", async () => {
  const legacyConfig = configWithBindings("legacy");
  await installConfig(legacyConfig);
  document.body.innerHTML = `<span id="legacy" mo-value="legacy"></span>`;
  startValueBindings();

  const legacy = document.querySelector<MarimoValueHost>("#legacy")!;
  let outgoingErrors = 0;
  legacy.addEventListener("marimo-value-error", () => outgoingErrors++);
  applyValues({ legacy: "ready" });

  commitRuntimeConfig(configWithBindings("incoming"));
  document.body.innerHTML = `<span id="incoming" mo-value="incoming"></span>`;
  await settleMutations();

  const incoming = document.querySelector<MarimoValueHost>("#incoming")!;
  let update: MarimoValueUpdatedDetail | undefined;
  incoming.addEventListener("marimo-value-updated", (event) => {
    update = event.detail;
  });
  applyValues({ incoming: "ready" });
  assert.equal(outgoingErrors, 0);
  assert.deepEqual(update, { selector: "incoming", value: "ready" });
});

test("response-wide read failures retain their structured error", async () => {
  await installConfig(configWithBindings("wide"));
  document.body.innerHTML = `<span id="wide" mo-value="wide"></span>`;
  startValueBindings();

  const wide = document.querySelector<MarimoValueHost>("#wide")!;
  let failure: MarimoValueErrorDetail | undefined;
  wide.addEventListener("marimo-value-error", (event) => {
    failure = event.detail;
  });
  applyValueReadResponse(["wide"], {
    values: {},
    errors: {
      "*": {
        code: "response-too-large",
        message: "The value response exceeds the aggregate byte limit.",
      },
    },
  });

  assert.deepEqual(failure, {
    selector: "wide",
    code: "response-too-large",
    message: "The value response exceeds the aggregate byte limit.",
  });
});
