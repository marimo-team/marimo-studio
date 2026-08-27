import { useEffect, useMemo } from "react";

import type { OutputReader } from "../../outputs/reader";
import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { RuntimeConnectionState } from "../cell-state";

import { getRuntimeConfig } from "../../runtime-config";
import { OutputOwnerReconciler } from "./output-owner-reconciler";

export const useOutputLifecycle = ({
  activeProjections,
  connectionState,
  readOutputs,
  projectionRevision,
  runtimeReady,
}: {
  activeProjections: ProjectionRequest[];
  connectionState: RuntimeConnectionState;
  readOutputs: OutputReader;
  projectionRevision: string;
  runtimeReady: boolean;
}): OutputReader => {
  const reconciler = useMemo(() => new OutputOwnerReconciler(readOutputs), [readOutputs]);
  const ownedReader = useMemo<OutputReader>(
    () => (request, signal) => reconciler.read(projectionRevision, request, signal),
    [projectionRevision, reconciler],
  );

  useEffect(() => () => reconciler.dispose(), [reconciler]);

  useEffect(() => {
    if (!runtimeReady || connectionState !== "OPEN") {
      reconciler.pause();
      return;
    }
    reconciler.update(projectionRevision, {
      revision: getRuntimeConfig().revision,
      projections: [],
      activeProjections,
    });
  }, [activeProjections, connectionState, projectionRevision, reconciler, runtimeReady]);

  return ownedReader;
};
