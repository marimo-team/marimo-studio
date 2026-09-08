import type {
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
import { defineOutputLoader, loadOutputs, scalarLoader } from "@marimo-team/marimo-export";
import { arrowTableLoader } from "@marimo-team/marimo-export/loader/arrow";
import { jsonLoader } from "@marimo-team/marimo-export/loader/json";
import { marimoCellLoader } from "@marimo-team/marimo-export/loader/marimo-cell";
import { marimoOutputLoader } from "@marimo-team/marimo-export/loader/marimo-output";

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

const valueLoader = (output: ExportOutput, loaders: ZeroPythonProjectionLoaders) => {
  if (output.codec === "marimo.json.v1") return loaders.json;
  if (output.codec === "marimo.scalar.v1") return loaders.scalar;
  if (output.codec === "apache.arrow.file.v1") return loaders.arrow;
  throw new TypeError(
    `Prepared value ${JSON.stringify(output.name)} uses unsupported codec ${JSON.stringify(output.codec)}.`,
  );
};

type ProjectionLoader = ZeroPythonProjectionLoaders[keyof ZeroPythonProjectionLoaders];
type LoadedProjection = Awaited<ReturnType<ProjectionLoader["load"]>>;
type PreparedArrow = Awaited<ReturnType<ZeroPythonProjectionLoaders["arrow"]["load"]>>;

const preparedValue = (
  output: ExportOutput,
  state: ExportState,
  loaded: LoadedProjection,
): PreparedValueSnapshot["value"] => {
  const fingerprint = `sha256:${state.fingerprint}`;
  if (output.codec === "apache.arrow.file.v1") {
    // SAFETY: valueLoader selects the Arrow loader for this output codec.
    const value = loaded as PreparedArrow;
    const sourceFingerprint = getMarimoDataSource(value)?.fingerprint ?? fingerprint;
    return { codec: "arrow-ipc-v1", fingerprint: sourceFingerprint, value };
  }
  return { codec: "json-v1", fingerprint, value: parseJsonValue(loaded) };
};

export const loadPreparedProjectionSnapshot = async (
  state: ExportState,
  projections: StudioProjectionBindings,
  loaders: ZeroPythonProjectionLoaders,
  signal: AbortSignal,
): Promise<PreparedProjectionSnapshot> => {
  const values = Object.entries(projections.values).map(([selector, name]) => ({
    selector,
    name,
    output: state.output(name),
  }));
  const selected: Record<string, ProjectionLoader> = Object.fromEntries([
    ...values.map(({ name, output }) => [name, valueLoader(output, loaders)]),
    ...Object.values(projections.outputs).map((name) => [name, loaders.output]),
    ...Object.values(projections.cells).map((name) => [name, loaders.cell]),
  ]);
  const loaded = await loadOutputs(state, selected, { signal });
  return {
    values: values.map(({ selector, name, output }) => ({
      selector,
      value: preparedValue(output, state, loaded[name]!),
    })),
    outputs: Object.entries(projections.outputs).map(([selector, name]) => ({
      selector,
      // SAFETY: This output name was paired with the native output snapshot loader.
      ...(loaded[name] as MarimoOutputSnapshot),
    })),
    cells: Object.entries(projections.cells).map(([alias, name]) => ({
      alias,
      // SAFETY: This output name was paired with the complete-cell snapshot loader.
      ...(loaded[name] as MarimoCellSnapshot),
    })),
  };
};
