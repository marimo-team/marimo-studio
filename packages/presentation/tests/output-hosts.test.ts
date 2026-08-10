import assert from "node:assert/strict";
import { afterEach, beforeAll, test } from "vite-plus/test";

import {
  type MarimoOutputElement,
  registerMarimoOutputElement,
  setOutputHostState,
} from "../src/outputs/host";

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
  assert.equal(host.id, "marimo-studio-output-report.figure");
  assert.equal(host.hasAttribute("data-hx-preserve"), true);

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
