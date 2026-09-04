import type {
  PreparedProjectionHandle,
  PreparedProjectionSnapshot,
} from "@marimo-studio/presentation/prepared-projections";
import type { RuntimeContext } from "@marimo-studio/runtime";
import type {
  ControlBinding,
  ExportOutput,
  ExportState,
  JsonObject,
  NotebookExport,
} from "@marimo-team/marimo-export";

import { NotebookExportError } from "@marimo-team/marimo-export";
import { vi } from "vite-plus/test";

import type { ZeroPythonRuntimeDependencies } from "../src/zero-python/composition.ts";

import { ZERO_PYTHON_RUNTIME_ID } from "../src/zero-python/runtime.ts";

export const projectionNames = {
  value: "value:doubled",
  output: "output:doubled",
  cell: "cell:chart",
} as const;

export const runtimeConfig = (): RuntimeContext["presentation"] => ({
  schema: 1,
  revision: "revision-1",
  projectionRevision: "4".repeat(64),
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: ZERO_PYTHON_RUNTIME_ID,
    instance: "1".repeat(64),
    data: { manifestUrl: "https://example.test/current", planDigest: "3".repeat(64) },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/dashboard/",
  supportUrl: "/dashboard/support/",
  showCellLogs: true,
  projectionTargets: { cells: {}, variables: {} },
  mounts: [],
  projectionPolicy: {
    maxActiveInstances: 512,
    maxUniqueCellTargets: 256,
    maxUniqueOutputTargets: 100,
    maxUniqueValueTargets: 100,
    maxTargetBytes: 4096,
    maxPathSteps: 64,
    maxInstanceIdBytes: 256,
  },
  runtimeBindings: { cellRefs: {} },
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: true,
  mode: "edit",
});

export const runtimeRoot = (projected = false): HTMLElement => {
  const owner = document.implementation.createHTMLDocument();
  const shell = owner.createElement("main");
  shell.id = "app-shell";
  if (projected) {
    shell.innerHTML = `
      <strong mo-value="metric"></strong>
      <marimo-output value="chart"></marimo-output>
      <marimo-cell name="summary"></marimo-cell>
    `;
  }
  const root = owner.createElement("div");
  root.id = "marimo-runtime-root";
  owner.body.append(shell, root);
  return root;
};

export const notebookExportFixture = (options: {
  readonly identity?: string;
  readonly inputs: readonly JsonObject[];
  readonly outputNames?: readonly string[];
  readonly controlBindings?: Readonly<Record<string, ControlBinding>>;
  readonly output?: (state: ExportState, name: string) => ExportOutput;
}): NotebookExport => {
  const identity = options.identity ?? "1".repeat(64);
  const states = new Map<string, ExportState>();
  let notebookExport: NotebookExport;
  const resolve = (inputs: JsonObject): ExportState => {
    const state = states.get(JSON.stringify(inputs));
    if (state === undefined) {
      throw new NotebookExportError("state_unavailable", "State is not prepared.");
    }
    return state;
  };
  for (const [index, inputs] of options.inputs.entries()) {
    const state = {
      aliases: Object.freeze(index === 0 ? ["baseline"] : [`state-${index}`]),
      fingerprint: (index + 1).toString(16).padStart(64, "0"),
      inputs: Object.freeze({ ...inputs }),
      get notebookExport() {
        return notebookExport;
      },
      output(name: string) {
        if (options.output === undefined) {
          throw new NotebookExportError("output_not_found", "Fixture output is unavailable.");
        }
        return options.output(this, name);
      },
      outputs: () => [],
      resolve(patch: JsonObject) {
        return resolve({ ...inputs, ...patch });
      },
    } satisfies ExportState;
    states.set(JSON.stringify(inputs), state);
  }
  const values = [...states.values()];
  notebookExport = {
    base: new URL(`https://example.test/export-${identity.slice(0, 4)}/`),
    identity,
    specSha256: "a".repeat(64),
    defaultState: values[0]!,
    notebook: { filename: "notebook.py", documentSha256: "2".repeat(64) },
    producer: {
      marimo: "0.24.0",
      marimoExport: "0.0.0",
      implementationSha256: "c".repeat(64),
    },
    inputNames: Object.freeze(Object.keys(options.inputs[0] ?? {})),
    controlBindings: Object.freeze({ ...options.controlBindings }),
    outputNames: Object.freeze([...(options.outputNames ?? [])]),
    states: () => values,
    state: (alias) => {
      const state = values.find((candidate) => candidate.aliases.includes(alias));
      if (state === undefined) {
        throw new NotebookExportError("state_not_found", "Fixture alias was not found.");
      }
      return state;
    },
    resolve,
    verify: async () => ({ states: values.length, outputs: 0, assets: 0, bytesVerified: 0 }),
  };
  return notebookExport;
};

export const studioManifest = (
  notebookExport: NotebookExport,
  inputs: JsonObject,
  projected = false,
) => {
  const state = notebookExport.resolve(inputs);
  return {
    schema: "marimo-studio.prepared.v1",
    prepared: {
      schema: "marimo-export.prepared.v1",
      instance: notebookExport.identity,
      export_url: notebookExport.base.href,
      inputs: state.inputs,
      state_fingerprint: state.fingerprint,
      refresh_interval_ms: 0,
    },
    projections: projected
      ? {
          values: { metric: projectionNames.value },
          outputs: { chart: projectionNames.output },
          cells: { summary: projectionNames.cell },
        }
      : { values: {}, outputs: {}, cells: {} },
    document_sha256: notebookExport.notebook.documentSha256,
    view: "dashboard",
    plan_digest: "3".repeat(64),
  };
};

export const rendererFixture = () => {
  const snapshots: PreparedProjectionSnapshot[] = [];
  const checkpoints: Array<{
    restore: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }> = [];
  const handle: PreparedProjectionHandle = {
    checkpoint: () => {
      const checkpoint = { restore: vi.fn(async () => {}), dispose: vi.fn() };
      checkpoints.push(checkpoint);
      return checkpoint;
    },
    replace: vi.fn(async (snapshot) => {
      snapshots.push(snapshot);
    }),
    restore: vi.fn(async () => {}),
    update: vi.fn(),
    updateControlBindings: vi.fn(),
    dispose: vi.fn(async () => {}),
  };
  return { checkpoints, handle, snapshots };
};

export const runtimeDependencies = (
  notebookExport: NotebookExport,
  manifests: readonly unknown[],
  renderer: PreparedProjectionHandle,
): ZeroPythonRuntimeDependencies => {
  let manifestIndex = 0;
  return {
    fetch: vi.fn(
      async () =>
        new Response(JSON.stringify(manifests[Math.min(manifestIndex++, manifests.length - 1)])),
    ),
    openExport: vi.fn(async () => notebookExport),
    loaders: {
      scalar: { codec: "marimo.scalar.v1", accepts: () => true, load: () => null },
      json: { codec: "marimo.json.v1", accepts: () => true, load: () => null },
      arrow: {
        codec: "apache.arrow.file.v1",
        accepts: () => true,
        load: () => {
          throw new Error("Empty fixture does not load Arrow projections.");
        },
      },
      output: {
        codec: "marimo.output.v1",
        accepts: () => true,
        load: () => {
          throw new Error("Empty fixture does not load output projections.");
        },
      },
      cell: {
        codec: "marimo.cell.v1",
        accepts: () => true,
        load: () => {
          throw new Error("Empty fixture does not load cell projections.");
        },
      },
    },
    mountProjections: vi.fn(() => renderer),
    theme: { current: () => undefined, subscribe: () => () => {} },
    setConnectionState: vi.fn(),
  };
};

export const installMarimoStudioGlobal = (): void => {
  globalThis.marimoStudio = {
    ready: async () => {},
    diagnostics: () => [],
    identity: () => ({ projectionRevision: "4".repeat(64), revision: "revision-1" }),
    projections: () => [],
    updateQuery: async () => {},
  };
};
