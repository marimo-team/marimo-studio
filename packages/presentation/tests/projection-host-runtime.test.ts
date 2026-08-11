import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import { ProjectionHostRuntime } from "../src/projections/host-runtime.ts";

afterEach(() => document.body.replaceChildren());

test("projection readiness covers cell, output, and value hosts", () => {
  document.body.innerHTML = `
    <marimo-cell name="summary" data-state="ready"></marimo-cell>
    <marimo-output value="report" data-state="loading"></marimo-output>
    <span mo-value="total" data-state="error"></span>
  `;
  const runtime = new ProjectionHostRuntime();

  assert.deepEqual(runtime.states(), ["ready", "loading", "error"]);
});

test("projection preparation assigns preservation identity through adapters", () => {
  document.body.innerHTML = `
    <marimo-cell name="summary"></marimo-cell>
    <marimo-output value="report.total"></marimo-output>
    <span mo-value="total"></span>
  `;
  const runtime = new ProjectionHostRuntime();

  runtime.prepare(document);

  const cell = document.querySelector("marimo-cell")!;
  const output = document.querySelector("marimo-output")!;
  const value = document.querySelector("[mo-value]")!;
  assert.equal(cell.id, "marimo-studio-cell-summary");
  assert.equal(cell.hasAttribute("data-hx-preserve"), true);
  assert.equal(output.id, "marimo-studio-output-report.total");
  assert.equal(output.hasAttribute("data-hx-preserve"), true);
  assert.equal(value.hasAttribute("data-hx-preserve"), false);
});
