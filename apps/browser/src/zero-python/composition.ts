import type {
  MountPreparedProjectionsOptions,
  PreparedProjectionHandle,
} from "@marimo-studio/presentation/prepared-projections";
import type { RuntimeContext } from "@marimo-studio/runtime";
import type { NotebookExport, OpenExportOptions } from "@marimo-team/marimo-export";
import type { PreparedPublicationRefreshOptions } from "@marimo-team/marimo-export/prepared";

import { parseJsonValue } from "@marimo-studio/presentation/json";
import {
  PreparedPublicationRefresh,
  PreparedStateController,
} from "@marimo-team/marimo-export/prepared";

import type { ZeroPythonRuntimeData } from "./metadata.ts";
import type { ZeroPythonProjectionLoaders } from "./projections.ts";

import { StudioPreparedInteractions } from "./interactions.ts";
import { StudioPreparedManifestSource } from "./metadata.ts";
import { StudioPreparedRenderer } from "./renderer.ts";
import { StudioPreparedStateApi } from "./state-api.ts";

type RuntimeConfig = RuntimeContext["presentation"];
type PreparedRefreshFailure = Parameters<
  NonNullable<PreparedPublicationRefreshOptions["onError"]>
>[0];

export interface ZeroPythonRuntimeDependencies {
  readonly fetch?: typeof globalThis.fetch;
  readonly openExport?: (
    base: string | URL,
    options?: OpenExportOptions,
  ) => Promise<NotebookExport>;
  readonly loaders: ZeroPythonProjectionLoaders;
  readonly mountProjections: (options: MountPreparedProjectionsOptions) => PreparedProjectionHandle;
  readonly theme: MountPreparedProjectionsOptions["theme"];
  readonly setConnectionState: (
    state: "connecting" | "ready" | "error",
    diagnostic?: { readonly code: string; readonly message: string; readonly hint: string },
  ) => void;
}

export interface StudioPreparedComposition {
  readonly renderer: StudioPreparedRenderer;
  readonly state: PreparedStateController;
  readonly stateApi: StudioPreparedStateApi;
  readonly interactions: StudioPreparedInteractions;
  readonly createRefresh: (
    data: ZeroPythonRuntimeData,
    expectedInstance?: string,
  ) => PreparedPublicationRefresh;
}

export const createStudioPreparedComposition = (options: {
  readonly root: HTMLElement;
  readonly context: () => {
    readonly config: RuntimeConfig;
    readonly data: ZeroPythonRuntimeData;
  };
  readonly dependencies: ZeroPythonRuntimeDependencies;
  readonly isDisposed: () => boolean;
}): StudioPreparedComposition => {
  const source = new StudioPreparedManifestSource(() => {
    const { config, data } = options.context();
    return {
      planDigest: data.planDigest,
      view: config.view,
    };
  }, options.dependencies.fetch);
  let interactions: StudioPreparedInteractions | undefined;
  const renderer = new StudioPreparedRenderer(
    options.dependencies.mountProjections({
      root: options.root,
      presentation: presentationConfig(options.context().config),
      theme: options.dependencies.theme,
      onControlInput: (input) => interactions?.controlInput(input, false),
      onPeerControlInput: (input) => interactions?.controlInput(input, true),
    }),
    source,
    options.dependencies.loaders,
  );
  const state = new PreparedStateController(renderer);
  interactions = new StudioPreparedInteractions(state, options.isDisposed);
  const stateApi = new StudioPreparedStateApi({
    snapshot: () => state.snapshot(),
    updateInputs: (patch) => {
      if (interactions === undefined) {
        throw new Error("Prepared runtime interactions are not mounted.");
      }
      return interactions.updateInputs(patch);
    },
  });
  return {
    renderer,
    state,
    stateApi,
    interactions,
    createRefresh: (data, expectedInstance) =>
      new PreparedPublicationRefresh(
        new URL(data.manifestUrl, globalThis.location.href),
        state,
        refreshOptions(source, options, expectedInstance),
      ),
  };
};

const refreshOptions = (
  source: StudioPreparedManifestSource,
  options: Parameters<typeof createStudioPreparedComposition>[0],
  expectedInstance?: string,
): PreparedPublicationRefreshOptions => {
  let initialInstance = expectedInstance;
  const base = {
    dependencies: {
      async fetchManifest(url: URL, fetchOptions?: Parameters<typeof source.fetch>[1]) {
        const manifest = await source.fetch(url, fetchOptions, initialInstance);
        initialInstance = undefined;
        return manifest;
      },
    },
    onError: (error: PreparedRefreshFailure) => {
      if (!options.isDisposed()) {
        console.warn(
          "Prepared runtime publication refresh failed. Retaining current state.",
          error,
        );
      }
    },
  };
  return options.dependencies.openExport === undefined
    ? base
    : { ...base, openExport: options.dependencies.openExport };
};

export const presentationConfig = (config: RuntimeConfig) => ({
  appConfig: parseJsonValue(config.appConfig),
  configOverrides: parseJsonValue(config.configOverrides),
  userConfig: parseJsonValue(config.userConfig),
});
