import { useEffect, useMemo } from "react";

import type { OutputReader } from "../../outputs/reader";
import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";

import { getRuntimeConfig } from "../../runtime-config";
import { OutputOwnerReconciler } from "./output-owner-reconciler";
import { createBatchedOutputReader } from "./output-read-batcher";

export const useOutputLifecycle = ({
  activeProjections,
  connectionState,
  readOutputs,
  projectionRevision,
  runtimeReady,
  refreshKey,
}: {
  activeProjections: ProjectionRequest[];
  connectionState: RuntimeConnectionState;
  readOutputs: OutputReader;
  projectionRevision: string;
  runtimeReady: boolean;
  refreshKey?: string;
}): OutputReader => {
  const reconciler = useMemo(() => new OutputOwnerReconciler(readOutputs), [readOutputs]);
  const ownedReader = useMemo<OutputReader>(
    () => (request, signal) => reconciler.read(projectionRevision, request, signal),
    [projectionRevision, reconciler],
  );
  const batchedReader = useMemo(() => createBatchedOutputReader(ownedReader), [ownedReader]);

  useEffect(() => () => reconciler.dispose(), [reconciler]);

  useEffect(() => {
    if (!runtimeReady || connectionState !== "OPEN") {
      reconciler.pause();
      return;
    }
    reconciler.update(
      projectionRevision,
      {
        revision: getRuntimeConfig().revision,
        projections: [],
        activeProjections,
      },
      refreshKey,
    );
  }, [
    activeProjections,
    connectionState,
    projectionRevision,
    reconciler,
    runtimeReady,
    refreshKey,
  ]);

  return batchedReader;
};
