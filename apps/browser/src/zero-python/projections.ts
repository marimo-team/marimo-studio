import type {
  PreparedJsonValue,
  PreparedProjectionSnapshot,
  PreparedValueSnapshot,
} from "@marimo-studio/presentation/prepared-projections";
import type {
  ExportOutput,
  ExportState,
  JsonValue,
  MarimoCellSnapshot,
  MarimoOutputSnapshot,
  OutputLoader,
} from "@marimo-team/marimo-export";

import {
  attachMarimoDataSource,
  getMarimoDataSource,
} from "@marimo-studio/marimo-frontend/arrow-table";
import { parseJsonValue } from "@marimo-studio/presentation/json";
import { defineOutputLoader, scalarLoader } from "@marimo-team/marimo-export";
import { arrowTableLoader } from "@marimo-team/marimo-export/loader/arrow";
import { jsonLoader } from "@marimo-team/marimo-export/loader/json";
import { marimoCellLoader } from "@marimo-team/marimo-export/loader/marimo-cell";
import { marimoOutputLoader } from "@marimo-team/marimo-export/loader/marimo-output";
import { isPreparedAbort } from "@marimo-team/marimo-export/prepared";

import type { StudioProjectionBindings } from "./metadata.ts";

export interface ZeroPythonProjectionLoaders {
  readonly scalar: ReturnType<typeof scalarLoader>;
  readonly json: OutputLoader<"marimo.json.v1", JsonValue>;
  readonly arrow: ReturnType<typeof preparedArrowLoader>;
  readonly output: OutputLoader<"marimo.output.v1", MarimoOutputSnapshot>;
  readonly cell: OutputLoader<"marimo.cell.v1", MarimoCellSnapshot>;
}

export const createZeroPythonProjectionLoaders = (): ZeroPythonProjectionLoaders => ({
  scalar: scalarLoader(),
  json: jsonLoader(),
  arrow: preparedArrowLoader(),
  output: marimoOutputLoader(),
  cell: marimoCellLoader(),
});

const preparedArrowLoader = () => {
  const base = arrowTableLoader();
  return defineOutputLoader({
    codec: "apache.arrow.file.v1" as const,
    accepts: (descriptor, mediaType) => base.accepts(descriptor, mediaType),
    async load(input) {
      const value = await base.load(input);
      input.signal?.throwIfAborted();
      return attachMarimoDataSource(value, {
        codec: "arrow-ipc-v1",
        fingerprint: `sha256:${input.descriptor.asset.sha256}`,
        bytes: input.payload.slice(),
      });
    },
  });
};

const loadPreparedValue = async (
  output: ExportOutput,
  state: ExportState,
  loaders: ZeroPythonProjectionLoaders,
  signal: AbortSignal,
): Promise<PreparedValueSnapshot["value"]> => {
  const fingerprint = `sha256:${state.fingerprint}`;
  if (output.codec === "marimo.json.v1") {
    return {
      codec: "json-v1" as const,
      fingerprint,
      value: studioJsonValue(await output.load(loaders.json, { signal })),
    };
  }
  if (output.codec === "marimo.scalar.v1") {
    const value = parseJsonValue(await output.load(loaders.scalar, { signal }));
    return { codec: "json-v1" as const, fingerprint, value: studioJsonValue(value) };
  }
  if (output.codec === "apache.arrow.file.v1") {
    const value = await output.load(loaders.arrow, { signal });
    const sourceFingerprint = getMarimoDataSource(value)?.fingerprint ?? fingerprint;
    return { codec: "arrow-ipc-v1" as const, fingerprint: sourceFingerprint, value };
  }
  throw new TypeError(
    `Prepared value ${JSON.stringify(output.name)} uses unsupported codec ${JSON.stringify(output.codec)}.`,
  );
};

const studioJsonValue = (value: JsonValue): PreparedJsonValue => {
  // SAFETY: marimo-export portable JSON is stricter than Studio's JSON wire contract.
  return structuredClone(value) as PreparedJsonValue;
};

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
  const values = Object.entries(projections.values).map(async ([selector, outputName]) => {
    const output = state.output(outputName);
    return {
      selector,
      value: await loadPreparedValue(output, state, loaders, controller.signal),
    };
  });
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
