export type CellPhase =
  | "connecting"
  | "missing"
  | "loading"
  | "error"
  | "stale"
  | "ready";

export const cellPhase = ({
  runtimeReady,
  hasCell,
  loading,
  disabled,
  hasOutput,
  failed,
  stale,
}: {
  runtimeReady: boolean;
  hasCell: boolean;
  loading: boolean;
  disabled: boolean;
  hasOutput: boolean;
  failed: boolean;
  stale: boolean;
}): CellPhase => {
  if (!hasCell) {
    return runtimeReady ? "missing" : "connecting";
  }
  if (loading) {
    return "loading";
  }
  if ((disabled && !hasOutput) || failed) {
    return "error";
  }
  if (disabled) {
    return "ready";
  }
  return stale ? "stale" : "ready";
};
