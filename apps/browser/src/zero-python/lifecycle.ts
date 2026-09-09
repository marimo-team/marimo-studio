import type {
  PreparedPublicationRefresh,
  PreparedStateController,
} from "@marimo-team/marimo-export/prepared";

import type { StudioPreparedStateApi } from "./state-api.ts";

export const disposeStudioPreparedRuntime = async (options: {
  readonly refresh: PreparedPublicationRefresh;
  readonly state: PreparedStateController;
  readonly stateApi: StudioPreparedStateApi;
}): Promise<void> => {
  const failures: unknown[] = [];
  await options.refresh.dispose().catch((error) => failures.push(error));
  await options.state.dispose().catch((error) => failures.push(error));
  try {
    options.stateApi.dispose();
  } catch (error) {
    failures.push(error);
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) {
    throw new AggregateError(failures, "Prepared runtime cleanup failed.");
  }
};
