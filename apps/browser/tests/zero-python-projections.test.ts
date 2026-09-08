import type {
  ExportOutput,
  ExportState,
  JsonValue,
  LoadOptions,
  MarimoCellSnapshot,
  MarimoOutputSnapshot,
  OutputCodec,
  OutputLoader,
} from "@marimo-team/marimo-export";

import { getMarimoDataSource } from "@marimo-studio/marimo-frontend/arrow-table";
import { tableFromArrays, tableToIPC } from "@uwdata/flechette";
import { expect, it } from "vite-plus/test";

import {
  createZeroPythonProjectionLoaders,
  loadPreparedProjectionSnapshot,
} from "../src/zero-python/projections.ts";
import { notebookExportFixture, projectionNames } from "./zero-python-fixture.ts";

it("adds authored host bindings to canonical export snapshots", async () => {
  const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
  const base = notebookExport.defaultState;
  const resources = {
    files: {},
    modelNotifications: [],
    functions: {},
    uiValues: {},
  };
  const loadSnapshot = async (name: string) => {
    if (name === projectionNames.value) {
      return { ready: true };
    }
    const projected = {
      projectionSha256: "7".repeat(64),
      output: { channel: "output" as const, mimetype: "text/plain", data: "ready" },
      resources,
    };
    if (name === projectionNames.output) {
      return {
        ...projected,
        schema: "marimo.output.v1" as const,
        ownerCellId: "owner-1",
      };
    }
    return {
      ...projected,
      schema: "marimo.cell.v1" as const,
      cell: {
        id: "cell-1",
        name: "summary",
        codeSha256: "6".repeat(64),
        config: {},
      },
      outcome: "completed" as const,
      console: [],
    };
  };
  const state = {
    ...base,
    output: (name: string): ExportOutput => output(base, name, () => loadSnapshot(name)),
  } satisfies ExportState;

  const snapshot = await loadPreparedProjectionSnapshot(
    state,
    {
      values: { metric: projectionNames.value },
      outputs: { chart: projectionNames.output },
      cells: { summary: projectionNames.cell },
    },
    createZeroPythonProjectionLoaders(),
    new AbortController().signal,
  );

  expect(snapshot.values).toEqual([
    {
      selector: "metric",
      value: {
        codec: "json-v1",
        fingerprint: `sha256:${base.fingerprint}`,
        value: { ready: true },
      },
    },
  ]);
  expect(snapshot.outputs[0]).toMatchObject({
    schema: "marimo.output.v1",
    selector: "chart",
    ownerCellId: "owner-1",
  });
  expect(snapshot.cells[0]).toMatchObject({
    schema: "marimo.cell.v1",
    alias: "summary",
    cell: { id: "cell-1" },
  });
});

it("preserves verified Arrow bytes and table behavior for Studio values", async () => {
  const table = tableFromArrays({ sport: ["Fencing", "Rowing"], athletes: [44, 51] });
  const bytes = tableToIPC(table, { format: "file" });
  if (bytes === null) throw new Error("Expected an in-memory Arrow file.");
  const digest = "b".repeat(64);
  const notebookExport = notebookExportFixture({
    inputs: [{ sport: "All sports" }],
    outputNames: [projectionNames.value],
    output: (state, name) => arrowOutput(state, name, bytes, digest),
  });

  const snapshot = await loadPreparedProjectionSnapshot(
    notebookExport.defaultState,
    { values: { athlete_facts: projectionNames.value }, outputs: {}, cells: {} },
    createZeroPythonProjectionLoaders(),
    new AbortController().signal,
  );
  const projected = snapshot.values[0]?.value;
  expect(projected?.codec).toBe("arrow-ipc-v1");
  if (projected?.codec !== "arrow-ipc-v1") throw new Error("Expected an Arrow value.");
  expect(projected.value.toArray()).toEqual([
    { sport: "Fencing", athletes: 44 },
    { sport: "Rowing", athletes: 51 },
  ]);
  const source = getMarimoDataSource(projected.value);
  expect(source?.fingerprint).toBe(`sha256:${digest}`);
  expect(source?.bytes).toEqual(bytes);
});

type FixtureLoad = (
  options?: LoadOptions,
) => Promise<JsonValue | MarimoCellSnapshot | MarimoOutputSnapshot>;

const output = (state: ExportState, name: string, fixtureLoad: FixtureLoad): ExportOutput => {
  const result: ExportOutput = {
    state,
    name,
    codec: "marimo.json.v1",
    mediaType: {
      raw: "application/json",
      essence: "application/json",
      type: "application",
      subtype: "json",
      parameters: new Map(),
    },
    descriptor: {
      codec: "marimo.json.v1",
      mediaType: "application/vnd.marimo.json.v1+json",
      provenance: { pythonType: "fixture.Value" },
      value: null,
    },
    async load<C extends OutputCodec, T>(
      _loader: OutputLoader<C, T>,
      options?: LoadOptions,
    ): Promise<T> {
      const value = await fixtureLoad(options);
      // SAFETY: Each fixture returns the payload expected by the loader selected for its output.
      return value as T;
    },
  };
  return result;
};

const arrowOutput = (
  state: ExportState,
  name: string,
  bytes: Uint8Array,
  digest: string,
): ExportOutput => {
  const descriptor = {
    codec: "apache.arrow.file.v1" as const,
    mediaType: "application/vnd.apache.arrow.file" as const,
    provenance: { pythonType: "polars.dataframe.frame.DataFrame" },
    asset: { sha256: digest, size: bytes.byteLength },
  };
  const mediaType = {
    raw: descriptor.mediaType,
    essence: descriptor.mediaType,
    type: "application",
    subtype: "vnd.apache.arrow.file",
    parameters: new Map<string, string>(),
  };
  return {
    state,
    name,
    codec: descriptor.codec,
    mediaType,
    descriptor,
    async load<C extends OutputCodec, T>(loader: OutputLoader<C, T>, options?: LoadOptions) {
      // SAFETY: This output advertises the Arrow codec and invokes its selected Arrow loader.
      return await (loader as OutputLoader<"apache.arrow.file.v1", T>).load({
        descriptor,
        mediaType,
        payload: bytes,
        signal: options?.signal,
      });
    },
  };
};
