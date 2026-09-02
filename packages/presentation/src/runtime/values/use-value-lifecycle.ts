import { useEffect, useMemo } from "react";

import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";

import { getRuntimeConfig } from "../../runtime-config";
import { ValueRequestError } from "../../values/remote";
import { ProjectionOwnerReconciler } from "../projection-owner-reconciler";
import { useLatest } from "../use-latest";

export const useValueLifecycle = ({
  activeProjections,
  connectionState,
  projectionRevision,
  readValues,
  runtimeReady,
}: {
  activeProjections: ProjectionRequest[];
  connectionState: RuntimeConnectionState;
  projectionRevision: string;
  readValues: ValueReader;
  runtimeReady: boolean;
}): ValueReader => {
  const reconciler = useMemo(
    () =>
      new ProjectionOwnerReconciler(
        readValues,
        1_000,
        (error) => error instanceof ValueRequestError && error.transient,
        () => [],
        true,
      ),
    [readValues],
  );
  const activeProjectionsRef = useLatest(activeProjections);
  const ownedReader = useMemo<ValueReader>(
    () => (request, signal) =>
      reconciler.read(
        projectionRevision,
        {
          ...request,
          activeProjections: activeProjectionsRef.current,
        },
        signal,
      ),
    [activeProjectionsRef, projectionRevision, reconciler],
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
