import type { EmbeddedCellExecutor } from "@marimo-studio/marimo-frontend/embedded-runtime";
import type { ProjectionRequest } from "@marimo-studio/protocol/projections";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import type { ResolvedProjection } from "../projections/resolution";
import type { WasmRuntimeData } from "./wasm-config";

import { resolveProjection } from "../projections/resolution";
import { ownRecordValue } from "../records";
import { throwIfWasmAborted, waitForWasmCaller } from "../values/wasm";

const resolveRequests = (
  config: RuntimeConfig,
  requests: readonly ProjectionRequest[],
): readonly ResolvedProjection[] =>
  requests.map((request) => {
    const mount = config.mounts.find((candidate) => candidate.id === request.siteId);
    const resolution = resolveProjection(config, {
      ...request,
      kind: mount?.kind ?? "value",
    });
    if (!resolution.ok) {
      throw new Error(resolution.error.message);
    }
    return resolution.value;
  });

const executionPlan = (
  config: RuntimeConfig,
  data: WasmRuntimeData,
  projections: readonly ResolvedProjection[],
  executed: ReadonlySet<string>,
) => {
  const required = new Set(
    projections.flatMap((projection) =>
      projection.dependencyClosure.map((reference) => {
        const runtimeCellId = ownRecordValue(config.runtimeBindings.cellRefs, reference);
        if (runtimeCellId === undefined) {
          throw new Error(`The WebAssembly runtime has no cell for ${JSON.stringify(reference)}.`);
        }
        return runtimeCellId;
      }),
    ),
  );
  const available = new Set(data.executionCells.map((cell) => cell.id));
  const missing = Array.from(required).find((runtimeCellId) => !available.has(runtimeCellId));
  if (missing !== undefined) {
    throw new Error(`The WebAssembly execution catalog has no cell ${JSON.stringify(missing)}.`);
  }
  return data.executionCells.filter((cell) => required.has(cell.id) && !executed.has(cell.id));
};

export interface WasmProjectionExecutor {
  prepare(
    config: RuntimeConfig,
    data: WasmRuntimeData,
    projections: readonly ResolvedProjection[],
    signal?: AbortSignal,
  ): Promise<void>;
  prepareRequests(
    config: RuntimeConfig,
    data: WasmRuntimeData,
    requests: readonly ProjectionRequest[],
    signal?: AbortSignal,
  ): Promise<void>;
}

export const createWasmProjectionExecutor = (
  executeCells: EmbeddedCellExecutor,
  ready: () => Promise<void>,
): WasmProjectionExecutor => {
  const executed = new Set<string>();
  let queue: Promise<void> = Promise.resolve();
  const prepare: WasmProjectionExecutor["prepare"] = (config, data, projections, signal) => {
    const operation = queue.then(async () => {
      throwIfWasmAborted(signal);
      await ready();
      throwIfWasmAborted(signal);
      const cells = executionPlan(config, data, projections, executed);
      if (cells.length === 0) {
        return;
      }
      await executeCells(cells);
      cells.forEach((cell) => executed.add(cell.id));
    });
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForWasmCaller(operation, signal);
  };
  return {
    prepare,
    async prepareRequests(config, data, requests, signal) {
      await prepare(config, data, resolveRequests(config, requests), signal);
    },
  };
};
