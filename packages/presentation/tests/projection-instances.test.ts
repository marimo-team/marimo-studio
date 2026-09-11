import { afterEach, expect, test } from "vite-plus/test";

import { renderedProjectionInstances } from "../src/projections/instances.ts";
import { resolveProjection } from "../src/projections/resolution.ts";
import {
  bindProjectionBindingStale,
  clearProjectionBindingStale,
} from "../src/projections/staleness.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

const dynamicConfig = () =>
  runtimeConfig({
    projectionTargets: {
      cells: {
        overview: {
          status: "ready",
          producer: "cell:v1:overview",
          producerLabel: "overview",
          dependencyClosure: ["cell:v1:overview"],
        },
        details: {
          status: "ready",
          producer: "cell:v1:details",
          producerLabel: "details",
          dependencyClosure: ["cell:v1:overview", "cell:v1:details"],
        },
      },
      variables: {
        metric: {
          status: "ready",
          producer: "cell:v1:overview",
          producerLabel: "overview",
          dependencyClosure: ["cell:v1:overview"],
        },
      },
    },
    mounts: [
      {
        id: "site:dynamic-cell",
        kind: "cell",
        source: { path: "src/App.tsx", line: 10, column: 7 },
        allowedTargets: null,
      },
      {
        id: "site:dynamic-value",
        kind: "value",
        source: { path: "src/App.tsx", line: 20, column: 7 },
        allowedTargets: ["metric"],
      },
    ],
    runtimeBindings: {
      cellRefs: {
        "cell:v1:overview": "runtime-overview",
        "cell:v1:details": "runtime-details",
      },
    },
  });

afterEach(() => {
  document.body.replaceChildren();
});

test("browser evidence reports compact mount facts", () => {
  commitRuntimeConfig(dynamicConfig());
  document.body.innerHTML = `
    <marimo-cell id="first" data-marimo-studio-site="site:dynamic-cell" name="overview"></marimo-cell>
    <strong data-marimo-studio-site="site:dynamic-value" mo-value="metric"></strong>
  `;

  const first = document.querySelector<HTMLElement>("#first")!;
  const initial = renderedProjectionInstances();
  expect(initial).toEqual([
    expect.objectContaining({
      mountId: "site:dynamic-cell",
      target: "overview",
      runtimeCellId: "runtime-overview",
      phase: "connecting",
    }),
    expect.objectContaining({
      mountId: "site:dynamic-value",
      target: "metric",
      runtimeCellId: "runtime-overview",
      phase: "connecting",
    }),
  ]);
  const instanceId = initial[0]?.instanceId;
  first.setAttribute("name", "details");
  expect(renderedProjectionInstances()[0]).toMatchObject({
    instanceId,
    target: "details",
    runtimeCellId: "runtime-details",
  });
  expect(first.dataset.marimoProducerRef).toBe("cell:v1:details");
});

test("runtime policy failures remain visible on mounted hosts", () => {
  const config = dynamicConfig();
  commitRuntimeConfig({
    ...config,
    projectionPolicy: {
      ...config.projectionPolicy,
      maxActiveInstances: 1,
    },
  });
  document.body.innerHTML = `
    <marimo-cell data-marimo-studio-site="site:dynamic-cell" name="overview"></marimo-cell>
    <marimo-cell data-marimo-studio-site="site:dynamic-cell" name="details"></marimo-cell>
  `;

  const instances = renderedProjectionInstances();
  expect(instances[0]?.error).toBeNull();
  expect(instances[1]?.error?.code).toBe("projection-instance-limit");
});

test("unresolved hosts do not consume the unique target quota", () => {
  const config = dynamicConfig();
  commitRuntimeConfig({
    ...config,
    mounts: config.mounts.map((mount) =>
      mount.id === "site:dynamic-value" ? { ...mount, allowedTargets: null } : mount,
    ),
    projectionPolicy: { ...config.projectionPolicy, maxUniqueValueTargets: 1 },
  });
  document.body.innerHTML = `
    <span data-marimo-studio-site="site:dynamic-value" mo-value="missing"></span>
    <span data-marimo-studio-site="site:dynamic-value" mo-value="metric"></span>
  `;

  const instances = renderedProjectionInstances();

  expect(instances[0]).toMatchObject({
    target: "missing",
    error: { code: "projection-value-variable-not-found" },
  });
  expect(instances[1]).toMatchObject({
    target: "metric",
    runtimeCellId: "runtime-overview",
    error: null,
  });
});

test("browser evidence excludes projection-like native output descendants", () => {
  const config = dynamicConfig();
  commitRuntimeConfig({
    ...config,
    projectionPolicy: { ...config.projectionPolicy, maxActiveInstances: 1 },
  });
  document.body.innerHTML = `
    <marimo-cell data-marimo-studio-site="site:dynamic-cell" name="overview"></marimo-cell>
    <div data-marimo-cell-output>
      <marimo-cell name="details">Native cell</marimo-cell>
      <marimo-output value="metric">Native output</marimo-output>
      <span mo-value="metric">Native value</span>
    </div>
  `;

  const instances = renderedProjectionInstances();

  expect(instances).toHaveLength(1);
  expect(instances[0]).toMatchObject({ target: "overview", error: null });
});

test("mount declarations authorize targets before notebook resolution", () => {
  const result = resolveProjection(dynamicConfig(), {
    siteId: "site:dynamic-value",
    instanceId: "projection-other",
    kind: "value",
    target: "other",
  });

  expect(result).toMatchObject({
    ok: false,
    error: { code: "projection-target-not-allowed" },
  });
});

test("value projections reject private attribute selection", () => {
  const config = dynamicConfig();
  const result = resolveProjection(
    {
      ...config,
      mounts: config.mounts.map((mount) =>
        mount.id === "site:dynamic-value" ? { ...mount, allowedTargets: null } : mount,
      ),
    },
    {
      siteId: "site:dynamic-value",
      instanceId: "projection-private",
      kind: "value",
      target: "metric.__dict__",
    },
  );

  expect(result).toMatchObject({
    ok: false,
    error: { code: "projection-target-invalid" },
  });
});

test("a local stale closure requests refreshed runtime bindings", () => {
  const config = dynamicConfig();
  const revision = "local-stale-bindings";
  let refreshes = 0;
  const unbind = bindProjectionBindingStale(() => refreshes++);
  commitRuntimeConfig({
    ...config,
    revision,
    runtimeBindings: { cellRefs: { "cell:v1:details": "runtime-details" } },
  });
  document.body.innerHTML = `
    <marimo-cell data-marimo-studio-site="site:dynamic-cell" name="details"></marimo-cell>
  `;

  renderedProjectionInstances();

  expect(refreshes).toBe(1);
  clearProjectionBindingStale(revision);
  unbind();
});

test("publishes current Lens labels without overwriting consumer-authored text", () => {
  commitRuntimeConfig(dynamicConfig());
  document.body.innerHTML = `
    <marimo-cell id="cell" data-marimo-studio-site="site:dynamic-cell" name="overview"></marimo-cell>
    <span id="value" data-marimo-studio-site="site:dynamic-value" mo-value="metric"></span>
  `;
  const cell = document.getElementById("cell")!;
  const value = document.getElementById("value")!;
  renderedProjectionInstances();
  expect(cell.getAttribute("data-marimo-lens-label")).toBe("overview");
  expect(value.getAttribute("data-marimo-lens-label")).toBe("metric");
  expect(value.getAttribute("data-marimo-lens-detail")).toBe("Value · overview");

  cell.setAttribute("name", "details");
  value.setAttribute("data-marimo-lens-label", "Revenue");
  renderedProjectionInstances();
  expect(cell.getAttribute("data-marimo-lens-label")).toBe("details");
  expect(value.getAttribute("data-marimo-lens-label")).toBe("Revenue");

  cell.setAttribute("name", "missing");
  value.setAttribute("mo-value", "missing");
  renderedProjectionInstances();
  expect(cell.hasAttribute("data-marimo-lens-label")).toBe(false);
  expect(value.hasAttribute("data-marimo-lens-detail")).toBe(false);
  expect(value.getAttribute("data-marimo-lens-label")).toBe("Revenue");
});
