import assert from "node:assert/strict";
import { afterEach, beforeAll, expect, test } from "vite-plus/test";

import {
  getOutputHosts,
  type MarimoOutputElement,
  registerMarimoOutputElement,
  setOutputHostState,
  subscribeOutputHosts,
} from "../src/outputs/host";
import { projectionRequestForHost } from "../src/projections/identity.ts";

beforeAll(() => registerMarimoOutputElement());

afterEach(() => document.body.replaceChildren());

test("rich output hosts publish lifecycle state and events", () => {
  document.body.innerHTML = '<marimo-output value="report.figure"></marimo-output>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const events: string[] = [];
  host.addEventListener("marimo-output-ready", () => events.push("ready"));
  host.addEventListener("marimo-output-updated", () => events.push("updated"));
  host.addEventListener("marimo-output-error", () => events.push("error"));

  assert.equal(host.dataset.state, "connecting");
  assert.equal(host.getAttribute("aria-busy"), "true");

  setOutputHostState(host, "ready", { selector: "report.figure" });
  setOutputHostState(host, "stale", { selector: "report.figure" });
  setOutputHostState(host, "ready", { selector: "report.figure" });
  setOutputHostState(host, "error", {
    selector: "report.figure",
    code: "output-format-error",
  });

  assert.deepEqual(events, ["ready", "updated", "error"]);
  assert.equal(host.dataset.state, "error");
  assert.equal(host.hasAttribute("aria-busy"), false);
});

test("changing an output target synchronously clears stale projection state", () => {
  document.body.innerHTML = '<marimo-output value="report.figure"></marimo-output>';
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  host.dataset.state = "ready";
  host.dataset.marimoProducerRef = "cell:v1:old";
  host.dataset.runtimeCellId = "old-cell";

  host.setAttribute("value", "report.table");

  assert.equal(host.dataset.state, "connecting");
  assert.equal(host.getAttribute("aria-busy"), "true");
  assert.equal(host.dataset.marimoProducerRef, undefined);
  assert.equal(host.dataset.runtimeCellId, undefined);
});

test("changing an output source site reconnects the same projection instance", () => {
  document.body.innerHTML = `
    <marimo-output
      value="report.figure"
      data-marimo-studio-site="site:output:first"
    ></marimo-output>
  `;
  const host = document.querySelector<MarimoOutputElement>("marimo-output")!;
  const initial = projectionRequestForHost(host, "output", host.valueSelector);
  let changes = 0;
  const unsubscribe = subscribeOutputHosts(() => changes++);
  host.dataset.state = "ready";
  host.dataset.marimoProducerRef = "cell:v1:old";

  host.dataset.marimoStudioSite = "site:output:second";

  expect(projectionRequestForHost(host, "output", host.valueSelector)).toMatchObject({
    siteId: "site:output:second",
    instanceId: initial.instanceId,
  });
  expect(host.dataset.state).toBe("connecting");
  expect(host.dataset.marimoProducerRef).toBeUndefined();
  expect(changes).toBe(1);
  unsubscribe();
});

test("the next duplicate output host becomes refresh-preserved when its owner leaves", async () => {
  document.body.innerHTML = `
    <marimo-output data-test-id="first" value="report"></marimo-output>
    <marimo-output data-test-id="second" value="report"></marimo-output>
  `;
  const first = document.querySelector<MarimoOutputElement>('[data-test-id="first"]')!;
  const second = document.querySelector<MarimoOutputElement>('[data-test-id="second"]')!;
  expect(first.id).toBe("marimo-studio-output-report");
  expect(second.id).toBe("");

  first.remove();
  await Promise.resolve();

  expect(second.id).toBe("marimo-studio-output-report");
  expect(second.hasAttribute("data-hx-preserve")).toBe(true);
});

test("output host ownership follows the composed document lifecycle", async () => {
  document.body.innerHTML = `
    <marimo-output data-test-id="first" value="report"></marimo-output>
    <marimo-output data-test-id="second" value="report"></marimo-output>
  `;
  const second = document.querySelector<MarimoOutputElement>('[data-test-id="second"]')!;
  expect(getOutputHosts().map((host) => host.dataset.testId)).toEqual(["first", "second"]);

  document.body.prepend(second);
  expect(getOutputHosts().map((host) => host.dataset.testId)).toEqual(["second", "first"]);

  second.dataset.marimoProducerRef = "cell:v1:report";
  second.dataset.runtimeCellId = "runtime-cell";
  const nativeOutput = document.createElement("div");
  nativeOutput.setAttribute("data-marimo-cell-output", "");
  const shadow = nativeOutput.attachShadow({ mode: "open" });
  document.body.append(nativeOutput);
  shadow.append(second);
  await Promise.resolve();

  expect(getOutputHosts().map((host) => host.dataset.testId)).toEqual(["first"]);
  expect(second.dataset.marimoProducerRef).toBeUndefined();
  expect(second.dataset.runtimeCellId).toBeUndefined();
  expect(second.dataset.state).toBeUndefined();

  document.body.append(second);
  await Promise.resolve();

  expect(getOutputHosts().map((host) => host.dataset.testId)).toEqual(["first", "second"]);
  expect(second.dataset.state).toBe("connecting");
});
