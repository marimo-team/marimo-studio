import type { ProjectionKind } from "@marimo-studio/protocol/projections";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { afterEach, beforeAll, expect, test, vi } from "vite-plus/test";

import type { WasmRuntimeData } from "../src/runtime/wasm-config";

import { registerMarimoCellElement } from "../src/cells/host.ts";
import { registerMarimoOutputElement } from "../src/outputs/host.ts";
import { mountedResolvedProjections } from "../src/projections/instances.ts";
import { createWasmMountedProjectionPreparation } from "../src/runtime/wasm-mounted-projections";
import { createWasmProjectionExecutor } from "../src/runtime/wasm-projection-execution";
import { runtimeConfig } from "./runtime-fixtures";

beforeAll(() => {
  registerMarimoCellElement();
  registerMarimoOutputElement();
});

afterEach(async () => {
  document.body.replaceChildren();
  await Promise.resolve();
});

const mountedConfig = (kind: Extract<ProjectionKind, "cell" | "output">): RuntimeConfig =>
  runtimeConfig({
    revision: `mounted-${kind}`,
    projectionTargets: {
      cells: {
        first: {
          status: "ready",
          producer: "cell:v1:first",
          dependencyClosure: ["cell:v1:first"],
        },
        second: {
          status: "ready",
          producer: "cell:v1:second",
          dependencyClosure: ["cell:v1:second"],
        },
        third: {
          status: "ready",
          producer: "cell:v1:third",
          dependencyClosure: ["cell:v1:third"],
        },
      },
      variables: {
        first: {
          status: "ready",
          producer: "cell:v1:first",
          dependencyClosure: ["cell:v1:first"],
        },
        second: {
          status: "ready",
          producer: "cell:v1:second",
          dependencyClosure: ["cell:v1:second"],
        },
        third: {
          status: "ready",
          producer: "cell:v1:third",
          dependencyClosure: ["cell:v1:third"],
        },
      },
    },
    mounts: [
      {
        id: `site:test:${kind}`,
        kind,
        source: { path: "src/App.tsx", line: 1, column: 1 },
        allowedTargets: null,
      },
    ],
    runtimeBindings: {
      cellRefs: {
        "cell:v1:first": "first-cell",
        "cell:v1:second": "second-cell",
        "cell:v1:third": "third-cell",
      },
    },
  });

const data: WasmRuntimeData = {
  code: "",
  filename: "notebook.py",
  version: "1",
  executionCells: [
    { id: "bootstrap-cell", code: "register_bridge()" },
    { id: "first-cell", code: "first = 1" },
    { id: "second-cell", code: "second = 2" },
    { id: "third-cell", code: "third = 3" },
  ],
  bootstrapCellId: "bootstrap-cell",
};

const appendHost = (kind: Extract<ProjectionKind, "cell" | "output">, target: string) => {
  const host = document.createElement(kind === "cell" ? "marimo-cell" : "marimo-output");
  host.setAttribute("data-marimo-studio-site", `site:test:${kind}`);
  host.setAttribute(kind === "cell" ? "name" : "value", target);
  document.body.append(host);
  return host;
};

const exerciseQueuedProjections = async (kind: Extract<ProjectionKind, "cell" | "output">) => {
  const config = mountedConfig(kind);
  let finishFirst = () => {};
  const firstExecution = new Promise<void>((resolve) => {
    finishFirst = resolve;
  });
  const executeCells = vi
    .fn<(cells: readonly { id: string; code: string }[]) => Promise<void>>()
    .mockImplementationOnce(() => firstExecution)
    .mockResolvedValue(undefined);
  const executor = createWasmProjectionExecutor(executeCells, async () => {});
  const mounted = createWasmMountedProjectionPreparation(config, data, executor);
  try {
    appendHost(kind, "first");
    await vi.waitFor(() => expect(executeCells).toHaveBeenCalledOnce());

    appendHost(kind, "second").remove();
    const third = appendHost(kind, "third");
    third.remove();
    document.body.append(third);
    await Promise.resolve();

    finishFirst();
    await executor.prepare(config, data, mountedResolvedProjections(config));
  } finally {
    mounted.dispose();
  }
  return executeCells;
};

for (const kind of ["cell", "output"] as const) {
  test(`drops disconnected and keeps reconnected ${kind} closures`, async () => {
    const executeCells = await exerciseQueuedProjections(kind);

    expect(executeCells).toHaveBeenCalledTimes(2);
    expect(executeCells).toHaveBeenNthCalledWith(1, [{ id: "first-cell", code: "first = 1" }]);
    expect(executeCells).toHaveBeenLastCalledWith([{ id: "third-cell", code: "third = 3" }]);
  });
}
