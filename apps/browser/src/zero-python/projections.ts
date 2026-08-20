import type { PreparedProjectionSnapshot } from "@marimo-studio/presentation/prepared-projections";
import type {
  ExportState,
  JsonValue,
  MarimoCellSnapshot,
  MarimoOutputSnapshot,
  OutputLoader,
} from "@marimo-team/marimo-export";

import { jsonLoader } from "@marimo-team/marimo-export/loader/json";
import { marimoCellLoader } from "@marimo-team/marimo-export/loader/marimo-cell";
import { marimoOutputLoader } from "@marimo-team/marimo-export/loader/marimo-output";
import { isPreparedAbort } from "@marimo-team/marimo-export/prepared";

import type { StudioProjectionBindings } from "./metadata.ts";

export interface ZeroPythonProjectionLoaders {
  readonly value: OutputLoader<"marimo.json.v1", JsonValue>;
  readonly output: OutputLoader<"marimo.output.v1", MarimoOutputSnapshot>;
  readonly cell: OutputLoader<"marimo.cell.v1", MarimoCellSnapshot>;
}

export const createZeroPythonProjectionLoaders = (): ZeroPythonProjectionLoaders => ({
  value: jsonLoader(),
  output: marimoOutputLoader(),
  cell: marimoCellLoader(),
});

export const loadPreparedProjectionSnapshot = async (
  state: ExportState,
  projections: StudioProjectionBindings,
  loaders: ZeroPythonProjectionLoaders,
  signal: AbortSignal,
): Promise<PreparedProjectionSnapshot> => {
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) {
    abort();
  }
  const values = Object.entries(projections.values).map(async ([selector, outputName]) => ({
    selector,
    value: await state.output(outputName).load(loaders.value, { signal: controller.signal }),
  }));
  const outputs = Object.entries(projections.outputs).map(async ([selector, outputName]) => {
    const snapshot = await state
      .output(outputName)
      .load(loaders.output, { signal: controller.signal });
    return {
      selector,
      ...snapshot,
    };
  });
  const cells = Object.entries(projections.cells).map(async ([alias, outputName]) => {
    const snapshot = await state
      .output(outputName)
      .load(loaders.cell, { signal: controller.signal });
    return {
      alias,
      ...snapshot,
    };
  });
  const loads = [...values, ...outputs, ...cells];
  let primaryFailure: unknown;
  const guarded = loads.map(async (load) => {
    try {
      return await load;
    } catch (error) {
      if (primaryFailure === undefined) {
        primaryFailure = error;
        controller.abort(error);
      }
      throw error;
    }
  });
  try {
    const settled = await Promise.allSettled(guarded);
    const failures = settled.flatMap((result) =>
      result.status === "rejected" && !isPreparedAbort(result.reason) ? [result.reason] : [],
    );
    if (primaryFailure !== undefined) {
      const primary = primaryFailure;
      const cleanup = failures.filter((failure) => failure !== primary);
      if (cleanup.length > 0) {
        throw new AggregateError([primary, ...cleanup], "Prepared projection loading failed.");
      }
      throw primary;
    }
    controller.signal.throwIfAborted();
    return {
      values: await Promise.all(values),
      outputs: await Promise.all(outputs),
      cells: await Promise.all(cells),
    };
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
