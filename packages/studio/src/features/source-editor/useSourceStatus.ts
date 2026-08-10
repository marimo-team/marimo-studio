import { useEffect, useState } from "react";

import type { SourcePhase, SourceState } from "./sync.ts";

const SOURCE_STATUS: Readonly<Record<Exclude<SourcePhase, "error">, string>> = {
  conflict: "Conflict",
  external: "Updated from disk",
  loading: "Loading",
  saved: "Saved ✓",
  saving: "Saving…",
};

const sourceStatus = (state: SourceState): string => {
  if (state.phase === "error") {
    return state.message ?? "Could not save";
  }
  return SOURCE_STATUS[state.phase];
};

export interface DisplaySourceStatus {
  message: string;
  phase: SourcePhase;
}

export const useSourceStatus = (state: SourceState): DisplaySourceStatus => {
  const [settledExternalState, setSettledExternalState] = useState<SourceState>();

  useEffect(() => {
    if (state.phase !== "external") {
      return;
    }
    const timer = globalThis.setTimeout(() => setSettledExternalState(state), 1_800);
    return () => globalThis.clearTimeout(timer);
  }, [state]);

  if (state.phase === "external" && state === settledExternalState) {
    return { message: SOURCE_STATUS.saved, phase: "saved" };
  }
  return { message: sourceStatus(state), phase: state.phase };
};
