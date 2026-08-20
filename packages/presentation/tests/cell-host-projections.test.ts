import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { MarimoCellElement } from "../src/cells/host.ts";
import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import { indexCells } from "../src/cells/bindings.ts";
import { serverRuntime } from "../src/runtime/catalog.ts";
import { projectCellHosts } from "../src/runtime/cells/cell-host-projections.ts";
import { runtimeCellFixture } from "./runtime-cell-fixture.ts";

const host = (name: string): MarimoCellElement => {
  const element = document.createElement("marimo-cell");
  element.setAttribute("name", name);
  Object.defineProperty(element, "cellName", { get: () => name });
  // SAFETY: The test supplies the `cellName` property used by the projection boundary.
  return element as MarimoCellElement;
};

const baseConfig = {
  schema: 1,
  revision: "revision-a",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    descriptor: serverRuntime.descriptor,
    instance: "server-instance",
    data: {
      fileKey: "/workspace/notebook.py",
      serverToken: "server-token",
      preserveSession: false,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {},
  outputBindings: {},
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  showCellLogs: false,
  dev: false,
  mode: "run",
} satisfies RuntimeConfig;

const config = (cellBindings: RuntimeConfig["cellBindings"]): RuntimeConfig => ({
  ...baseConfig,
  cellBindings,
});

test("cell hosts require own bindings for inherited-looking names", () => {
  const cell = runtimeCellFixture({ id: "reserved-cell", name: "reserved" });
  const cells = indexCells([cell]);
  const unknown = projectCellHosts(config({}), cells, [host("toString")])[0];
  const ownBindings = Object.fromEntries([
    ["toString", { kind: "id" as const, value: "reserved-cell" }],
  ]);
  const reserved = projectCellHosts(config(ownBindings), cells, [host("toString")])[0];

  assert.equal(unknown?.kind, "cell");
  assert.equal(unknown?.kind === "cell" && unknown.bindingPresent, false);
  assert.equal(unknown?.kind === "cell" && unknown.cell, undefined);
  assert.equal(reserved?.kind, "cell");
  assert.equal(reserved?.kind === "cell" && reserved.bindingPresent, true);
  assert.equal(reserved?.kind === "cell" && reserved.cell, cell);
});
