import { useEffect } from "react";

import type { OutputReader } from "../../outputs/reader";
import type { RuntimeConnectionState } from "../cell-state";

import { useLatest } from "../use-latest";

export const useOutputLifecycle = ({
  activeSelectors,
  connectionState,
  readOutputs,
  revision,
  runtimeReady,
}: {
  activeSelectors: string[];
  connectionState: RuntimeConnectionState;
  readOutputs: OutputReader;
  revision: string;
  runtimeReady: boolean;
}): void => {
  const revisionRef = useLatest(revision);

  useEffect(() => {
    if (!runtimeReady || connectionState !== "OPEN") {
      return;
    }
    const controller = new AbortController();
    void readOutputs(
      { revision: revisionRef.current, selectors: [], activeSelectors },
      controller.signal,
    ).catch(() => {});
    return () => controller.abort();
  }, [activeSelectors, connectionState, readOutputs, revisionRef, runtimeReady]);
};
