import type {
  PreparedProjectionSnapshot,
  PreparedValueSnapshot,
} from "@marimo-studio/presentation/prepared-projections";
import type {
  BlobAssetLoader,
  ExportOutput,
  ExportState,
  JsonValue,
  MarimoCellOutput,
  MarimoCellSnapshot,
  MarimoOutputSnapshot,
  OutputLoader,
} from "@marimo-team/marimo-export";

import {
  attachMarimoDataSource,
  getMarimoDataSource,
} from "@marimo-studio/marimo-frontend/arrow-table";
import { parseJsonValue } from "@marimo-studio/presentation/json";
import {
  defineBlobAssetLoader,
  defineOutputLoader,
  loadOutputs,
  scalarLoader,
} from "@marimo-team/marimo-export";
import { arrowTableLoader } from "@marimo-team/marimo-export/loader/arrow";
import { jsonLoader } from "@marimo-team/marimo-export/loader/json";
import { marimoCellLoader } from "@marimo-team/marimo-export/loader/marimo-cell";
import { marimoOutputLoader } from "@marimo-team/marimo-export/loader/marimo-output";
import { z } from "zod";

import type { StudioProjectionBindings } from "./metadata.ts";

export interface ZeroPythonProjectionLoaders {
  readonly scalar: ReturnType<typeof scalarLoader>;
  readonly json: OutputLoader<"marimo.json.v1", JsonValue>;
  readonly arrow: ReturnType<typeof preparedArrowLoader>;
  readonly output: OutputLoader<"marimo.output.v1", MarimoOutputSnapshot>;
  readonly media: (ownerCellId: string) => BlobAssetLoader<MarimoOutputSnapshot>;
  readonly cell: OutputLoader<"marimo.cell.v1", MarimoCellSnapshot>;
}

export const createZeroPythonProjectionLoaders = (): ZeroPythonProjectionLoaders => ({
  scalar: scalarLoader(),
  json: jsonLoader(),
  arrow: preparedArrowLoader(),
  output: marimoOutputLoader(),
  media: mediaOutputLoader,
  cell: marimoCellLoader(),
});

const base64 = (data: Uint8Array): string => {
  let binary = "";
  for (let index = 0; index < data.length; index += 0x8000) {
    binary += String.fromCharCode(...data.subarray(index, index + 0x8000));
  }
  return btoa(binary);
};

// The media exporter records the display size of a PNG it renders at a higher
// pixel density.
const displaySizeSchema = z.object({
  width: z.int().min(1).optional(),
  height: z.int().min(1).optional(),
});

// An output site with an accept list exports its value in the first accepted
// media type. Hosts show it as marimo output data, matching the Python
// runtime's media_output(): a base64 data URL, wrapped in a marimo mimebundle
// with the display size the media exporter records for a high-density image.
const mediaOutputLoader = (ownerCellId: string) =>
  defineBlobAssetLoader<MarimoOutputSnapshot>({
    mediaTypes: () => true,
    load({ descriptor, payload, signal }) {
      signal?.throwIfAborted();
      const mimetype = payload.mediaType.essence;
      const url = `data:${mimetype};base64,${base64(payload.data)}`;
      // Parsing keeps only the size fields the metadata holds.
      const size = displaySizeSchema.parse(payload.metadata);
      const output: MarimoCellOutput =
        size.width === undefined && size.height === undefined
          ? { channel: "output", mimetype, data: url }
          : {
              channel: "output",
              mimetype: "application/vnd.marimo+mimebundle",
              data: JSON.stringify({ [mimetype]: url, __metadata__: { [mimetype]: size } }),
            };
      return Object.freeze({
        schema: "marimo.output.v1",
        projectionSha256: descriptor.asset.sha256,
        ownerCellId,
        output: Object.freeze(output),
        resources: EMPTY_RESOURCES,
      });
    },
  });

const EMPTY_RESOURCES = Object.freeze({
  files: Object.freeze({}),
  modelNotifications: Object.freeze([]),
  functions: Object.freeze({}),
  uiValues: Object.freeze({}),
});

// The Prepared compiler exports every output that accepts media as a BlobAsset.
const outputLoader = (
  output: ExportOutput,
  loaders: ZeroPythonProjectionLoaders,
  ownerCellId: () => string,
) =>
  output.codec === "marimo.blob-asset.msgpack.v1" ? loaders.media(ownerCellId()) : loaders.output;

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

type ProjectionLoader =
  | ZeroPythonProjectionLoaders[Exclude<keyof ZeroPythonProjectionLoaders, "media">]
  | ReturnType<ZeroPythonProjectionLoaders["media"]>;
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
  ownerCell: (selector: string) => string,
  signal: AbortSignal,
): Promise<PreparedProjectionSnapshot> => {
  const values = Object.entries(projections.values).map(([selector, name]) => ({
    selector,
    name,
    output: state.output(name),
  }));
  const selected: Record<string, ProjectionLoader> = Object.fromEntries([
    ...values.map(({ name, output }) => [name, valueLoader(output, loaders)]),
    ...Object.entries(projections.outputs).map(([selector, name]) => [
      name,
      outputLoader(state.output(name), loaders, () => ownerCell(selector)),
    ]),
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
      // SAFETY: outputLoader pairs every output with a loader that returns a marimo output snapshot.
      ...(loaded[name] as MarimoOutputSnapshot),
    })),
    cells: Object.entries(projections.cells).map(([alias, name]) => ({
      alias,
      // SAFETY: This output name was paired with the complete-cell snapshot loader.
      ...(loaded[name] as MarimoCellSnapshot),
    })),
  };
};
