import type { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";

import { WebSocketState as ConnectionState } from "@marimo-studio/marimo-frontend/runtime";
import { useEffect } from "react";

import type { OutputReader } from "../../outputs/reader";

import { useLatest } from "../use-latest";

export const useOutputLifecycle = ({
  activeSelectors,
  connectionState,
  readOutputs,
  revision,
  runtimeReady,
}: {
  activeSelectors: string[];
  connectionState: WebSocketState;
  readOutputs: OutputReader;
  revision: string;
  runtimeReady: boolean;
}): void => {
  const revisionRef = useLatest(revision);

  useEffect(() => {
    if (!runtimeReady || connectionState !== ConnectionState.OPEN) {
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
