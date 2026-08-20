import type { PreparedProjectionCheckpoint } from "@marimo-studio/presentation/prepared-projections";
import type { RuntimeContext } from "@marimo-studio/runtime";
import type {
  PreparedPublication,
  PreparedPublicationRefresh,
  PreparedStateController,
  PreparedStateSnapshot,
} from "@marimo-team/marimo-export/prepared";
import type { JsonObject } from "@marimo-team/portable-json";

import { isNotebookExportError } from "@marimo-team/marimo-export";

import type { AuthoredProjectionHosts } from "./hosts.ts";
import type { ZeroPythonRuntimeData } from "./metadata.ts";

type RuntimeConfig = RuntimeContext["presentation"];

export interface StudioRevisionSnapshot {
  readonly config: RuntimeConfig;
  readonly data: ZeroPythonRuntimeData;
  readonly hosts: AuthoredProjectionHosts;
  readonly pendingInputs: JsonObject | undefined;
  readonly publication: PreparedPublication;
  readonly renderer: PreparedProjectionCheckpoint;
  readonly refresh: PreparedPublicationRefresh;
}

export const studioRevisionSnapshot = (options: {
  readonly config: RuntimeConfig;
  readonly data: ZeroPythonRuntimeData;
  readonly hosts: AuthoredProjectionHosts;
  readonly state: PreparedStateSnapshot;
  readonly renderer: PreparedProjectionCheckpoint;
  readonly refresh: PreparedPublicationRefresh;
}): StudioRevisionSnapshot => {
  if (options.state.current === undefined) {
    throw new Error("The prepared publication is still starting.");
  }
  return Object.freeze({
    config: options.config,
    data: options.data,
    hosts: options.hosts,
    pendingInputs: options.state.pendingInputs,
    publication: options.state.current,
    renderer: options.renderer,
    refresh: options.refresh,
  });
};

export const restorePreparedState = async (
  state: PreparedStateController,
  previous: StudioRevisionSnapshot,
): Promise<void> => {
  const current = state.snapshot();
  if (current.pendingInputs !== undefined && current.current !== undefined) {
    await state.updateInputs(current.current.state.inputs);
  }
  await state.replacePublication(previous.publication);
  if (previous.pendingInputs === undefined) {
    return;
  }
  try {
    await state.updateInputs(previous.pendingInputs);
  } catch (error) {
    if (!isNotebookExportError(error) || error.code !== "state_unavailable") {
      throw error;
    }
  }
};

export const restoreStudioRevision = async (options: {
  readonly currentRefresh: PreparedPublicationRefresh;
  readonly createRefresh: (
    data: ZeroPythonRuntimeData,
    expectedInstance?: string,
  ) => PreparedPublicationRefresh;
  readonly previous: StudioRevisionSnapshot;
  readonly restoreContext: () => void;
  readonly state: PreparedStateController;
}): Promise<PreparedPublicationRefresh> => {
  await options.currentRefresh.dispose();
  options.restoreContext();
  await restorePreparedState(options.state, options.previous);
  await options.previous.renderer.restore();
  options.previous.renderer.dispose();
  const refresh = options.createRefresh(
    options.previous.data,
    options.previous.publication.manifest.instance,
  );
  refresh.syncPolling();
  return refresh;
};
