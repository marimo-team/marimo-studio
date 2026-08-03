export type ValueCellPhase = "loading" | "stale" | "ready" | "error";

export const valueCellPhase = ({
  runtimeReady,
  hasCell,
  disabled,
  status,
  version,
  errored,
  stale,
  deliveryTimedOut,
}: {
  runtimeReady: boolean;
  hasCell: boolean;
  disabled: boolean;
  status: string;
  version: number | null;
  errored: boolean;
  stale: boolean;
  deliveryTimedOut: boolean;
}): ValueCellPhase => {
  if (!runtimeReady) {
    return "loading";
  }
  if (!hasCell) {
    return deliveryTimedOut ? "error" : "loading";
  }
  if (disabled || status === "disabled-transitively" || errored) {
    return "error";
  }
  if (status !== "idle" || version === null) {
    return "loading";
  }
  if (stale) {
    return "stale";
  }
  return "ready";
};
