import assert from "node:assert/strict";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, expect, test } from "vite-plus/test";

import {
  getCellHosts,
  type MarimoCellElement,
  registerMarimoCellElement,
  subscribeCellHosts,
} from "../src/cells/host.ts";
import { indexCells } from "../src/cells/index.ts";
import { projectionRequestForHost } from "../src/projections/identity.ts";
import {
  bindProjectionBindingStale,
  clearProjectionBindingStale,
} from "../src/projections/staleness.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { projectCellHosts } from "../src/runtime/cells/cell-host-projections.ts";
import { RuntimeCellPortals } from "../src/runtime/cells/RuntimeCellPortals.tsx";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures.ts";

beforeAll(() => registerMarimoCellElement());

afterEach(() => document.body.replaceChildren());

test("commits cell projection metadata with the portal lifecycle", async () => {
  const config = {
    ...projectionRuntimeConfig([projectionRequest("overview", "cell")]),
    projectionRevision: "f".repeat(64),
    runtimeBindings: { cellRefs: { "cell:v1:other": "other-cell" } },
  };
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <marimo-cell
      name="overview"
      data-marimo-studio-site="site:cell:overview"
    ></marimo-cell>
    <div id="root"></div>
  `;
  const host = document.querySelector<MarimoCellElement>("marimo-cell")!;
  const cells = indexCells([]);
  let staleBindingNotifications = 0;
  const unbind = bindProjectionBindingStale(() => staleBindingNotifications++);
  const [projected] = projectCellHosts(config, cells, [host]);

  expect(host.dataset.marimoStudioInstance).toBeUndefined();
  expect(host.dataset.marimoProducerRef).toBeUndefined();
  expect(staleBindingNotifications).toBe(0);

  const root = createRoot(document.querySelector("#root")!);
  await act(async () => {
    root.render(
      createElement(RuntimeCellPortals, {
        cells,
        hosts: [host],
        runtimeReady: false,
        onSubmitStdin: () => {},
      }),
    );
  });

  expect(host.dataset.marimoStudioInstance).toBe(
    projected?.binding.resolution.ok
      ? projected.binding.resolution.value.request.instanceId
      : undefined,
  );
  expect(host.dataset.marimoProducerRef).toBe("cell:v1:overview");
  expect(host.dataset.marimoProjectionKind).toBe("cell");
  expect(host.dataset.marimoProjectionTarget).toBe("overview");
  expect(staleBindingNotifications).toBe(1);

  await act(async () => root.unmount());

  expect(host.dataset.marimoStudioInstance).toBeUndefined();
  expect(host.dataset.marimoProducerRef).toBeUndefined();
  expect(host.dataset.marimoProjectionKind).toBeUndefined();
  expect(host.dataset.marimoProjectionTarget).toBeUndefined();
  clearProjectionBindingStale(config.projectionRevision);
  unbind();
});

test("changing a cell target synchronously clears stale projection state", () => {
  document.body.innerHTML = '<marimo-cell name="overview"></marimo-cell>';
  const host = document.querySelector<MarimoCellElement>("marimo-cell")!;
  host.dataset.state = "ready";
  host.dataset.marimoProducerRef = "cell:v1:old";
  host.dataset.runtimeCellId = "old-cell";

  host.setAttribute("name", "details");

  assert.equal(host.dataset.state, "connecting");
  assert.equal(host.getAttribute("aria-busy"), "true");
  assert.equal(host.dataset.marimoProducerRef, undefined);
  assert.equal(host.dataset.runtimeCellId, undefined);
});

test("changing a cell source site reconnects the same projection instance", () => {
  document.body.innerHTML = `
    <marimo-cell name="overview" data-marimo-studio-site="site:cell:first"></marimo-cell>
  `;
  const host = document.querySelector<MarimoCellElement>("marimo-cell")!;
  const initial = projectionRequestForHost(host, "cell", host.cellName);
  let changes = 0;
  const unsubscribe = subscribeCellHosts(() => changes++);
  host.dataset.state = "ready";
  host.dataset.marimoProducerRef = "cell:v1:old";

  host.dataset.marimoStudioSite = "site:cell:second";

  expect(projectionRequestForHost(host, "cell", host.cellName)).toMatchObject({
    siteId: "site:cell:second",
    instanceId: initial.instanceId,
  });
  expect(host.dataset.state).toBe("connecting");
  expect(host.dataset.marimoProducerRef).toBeUndefined();
  expect(changes).toBe(1);
  unsubscribe();
});

test("cell host ownership follows the composed document lifecycle", async () => {
  document.body.innerHTML = `
    <marimo-cell data-test-id="first" name="summary"></marimo-cell>
    <marimo-cell data-test-id="second" name="summary"></marimo-cell>
  `;
  const second = document.querySelector<MarimoCellElement>('[data-test-id="second"]')!;
  expect(getCellHosts().map((host) => host.dataset.testId)).toEqual(["first", "second"]);

  document.body.prepend(second);
  expect(getCellHosts().map((host) => host.dataset.testId)).toEqual(["second", "first"]);

  second.dataset.marimoProducerRef = "cell:v1:summary";
  second.dataset.runtimeCellId = "runtime-cell";
  const nativeOutput = document.createElement("div");
  nativeOutput.setAttribute("data-marimo-cell-output", "");
  const shadow = nativeOutput.attachShadow({ mode: "open" });
  document.body.append(nativeOutput);
  shadow.append(second);
  await Promise.resolve();

  expect(getCellHosts().map((host) => host.dataset.testId)).toEqual(["first"]);
  expect(second.dataset.marimoProducerRef).toBeUndefined();
  expect(second.dataset.runtimeCellId).toBeUndefined();
  expect(second.dataset.state).toBeUndefined();

  document.body.append(second);
  await Promise.resolve();

  expect(getCellHosts().map((host) => host.dataset.testId)).toEqual(["first", "second"]);
  expect(second.dataset.state).toBe("connecting");
});
