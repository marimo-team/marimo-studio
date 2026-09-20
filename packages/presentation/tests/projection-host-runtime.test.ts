import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import { ProjectionHostRuntime } from "../src/projections/host-runtime.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

afterEach(() => document.body.replaceChildren());

test("projection readiness covers cell, output, and value hosts", () => {
  document.body.innerHTML = `
    <marimo-cell name="summary" data-state="ready"></marimo-cell>
    <marimo-output value="report" data-state="loading"></marimo-output>
    <span mo-value="total" data-state="error"></span>
  `;
  const runtime = new ProjectionHostRuntime();
  commitRuntimeConfig(runtimeConfig());
  runtime.connect();
  document.querySelector<HTMLElement>("marimo-cell")!.dataset.state = "ready";
  document.querySelector<HTMLElement>("marimo-output")!.dataset.state = "loading";
  document.querySelector<HTMLElement>("[mo-value]")!.dataset.state = "error";

  assert.deepEqual(new Set(runtime.states()), new Set(["ready", "loading", "error"]));
  runtime.disconnect();
});

test("committing a shell swap moves retained hosts into the incoming tree", () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-cell
        id="marimo-studio-cell-summary"
        name="summary"
        data-marimo-studio-preserve
      ><em>Rendered cell</em></marimo-cell>
      <marimo-output
        id="marimo-studio-output-report"
        value="report"
        data-marimo-studio-preserve
      ><strong>Rendered report</strong></marimo-output>
      <strong mo-value="metric" data-marimo-studio-site="site-value">42</strong>
    </main>
  `;
  const liveCell = document.querySelector<HTMLElement>("marimo-cell")!;
  const liveOutput = document.querySelector<HTMLElement>("marimo-output")!;
  const liveValue = document.querySelector<HTMLElement>("[mo-value]")!;
  const liveCellOutput = liveCell.firstElementChild;
  const liveOutputRenderer = liveOutput.firstElementChild;
  const next = new DOMParser().parseFromString(
    `<main id="app-shell">
      <marimo-cell
        id="marimo-studio-cell-summary"
        name="summary"
        aria-label="Updated summary"
        data-marimo-studio-preserve
      ></marimo-cell>
      <marimo-output
        id="marimo-studio-output-report"
        value="report"
        aria-label="Updated report"
        data-marimo-studio-preserve
      ></marimo-output>
      <strong
        mo-value="metric"
        aria-label="Updated metric"
        data-marimo-studio-site="site-value"
      ></strong>
    </main>`,
    "text/html",
  );
  const runtime = new ProjectionHostRuntime();
  runtime.prepare(document);
  runtime.prepare(next);
  const incoming = document.importNode(next.querySelector<HTMLElement>("#app-shell")!, true);
  const staged = runtime.stagePreservation(incoming, document);
  const current = document.querySelector<HTMLElement>("#app-shell")!;
  current.before(incoming);
  staged.commit();
  current.remove();

  staged.finalize();

  assert.equal(document.getElementById("marimo-studio-cell-summary"), liveCell);
  assert.equal(document.getElementById("marimo-studio-output-report"), liveOutput);
  assert.equal(document.getElementById("marimo-studio-value-site-value"), liveValue);
  assert.equal(liveCell.getAttribute("aria-label"), "Updated summary");
  assert.equal(liveOutput.getAttribute("aria-label"), "Updated report");
  assert.equal(liveValue.getAttribute("aria-label"), "Updated metric");
  assert.equal(liveCell.firstElementChild, liveCellOutput);
  assert.equal(liveOutput.firstElementChild, liveOutputRenderer);
  assert.equal(liveValue.textContent, "42");
});

test("rolling back staged preservation restores live host attributes", () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-output
        id="marimo-studio-output-report"
        value="report"
        class="current"
        data-marimo-studio-preserve
      ><strong>Rendered report</strong></marimo-output>
    </main>
  `;
  const live = document.querySelector<HTMLElement>("marimo-output")!;
  const next = new DOMParser().parseFromString(
    `<main id="app-shell">
      <marimo-output
        id="marimo-studio-output-report"
        value="report"
        class="incoming"
        data-marimo-studio-preserve
      ></marimo-output>
    </main>`,
    "text/html",
  );
  const runtime = new ProjectionHostRuntime();
  const incoming = document.importNode(next.querySelector<HTMLElement>("#app-shell")!, true);
  const staged = runtime.stagePreservation(incoming, document);
  assert.equal(live.className, "incoming");
  const current = document.querySelector<HTMLElement>("#app-shell")!;
  current.before(incoming);
  staged.commit();
  assert.equal(incoming.querySelector("marimo-output"), live);
  assert.equal(current.querySelector("marimo-output"), null);

  staged.rollback();

  assert.equal(current.querySelector("marimo-output"), live);
  assert.notEqual(incoming.querySelector("marimo-output"), live);
  assert.equal(live.isConnected, true);
  assert.equal(live.className, "current");
  assert.equal(live.textContent, "Rendered report");
});

test.each([
  ["marimo-cell", 'name="summary"'],
  ["marimo-output", 'value="report"'],
  ["span", 'mo-value="metric" data-marimo-studio-site="site-value"'],
])("preserving %s leaves matching native output nodes with their owner", (tag, attributes) => {
  document.body.innerHTML =
    `<section data-marimo-cell-output><${tag} id="matching" ${attributes} ` +
    `class="native">Native content</${tag}></section>`;
  const nativeParent = document.querySelector("section")!;
  const native = nativeParent.firstElementChild!;
  const incoming = new DOMParser()
    .parseFromString(
      `<main><${tag} id="matching" ${attributes} class="authored"></${tag}></main>`,
      "text/html",
    )
    .querySelector("main")!;
  const authored = incoming.firstElementChild;
  const runtime = new ProjectionHostRuntime();
  runtime.prepare(incoming);

  const staged = runtime.stagePreservation(incoming, document);
  document.body.append(incoming);
  staged.commit();
  staged.finalize();

  assert.equal(native.parentElement, nativeParent);
  assert.equal(native.className, "native");
  assert.equal(native.textContent, "Native content");
  assert.equal(incoming.firstElementChild, authored);
});
