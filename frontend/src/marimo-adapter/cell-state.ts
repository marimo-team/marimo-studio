export type CellPhase =
  | "connecting"
  | "missing"
  | "loading"
  | "error"
  | "stale"
  | "ready";

export type CellDeliveryPhase =
  | "received"
  | "waiting"
  | "timed-out"
  | "missing";

export const CELL_DELIVERY_TIMEOUT_MS = 10_000;

export interface RuntimeConnectionDiagnostic {
  code: string;
  message: string;
  hint: string;
}

export const runtimeConnectionDiagnostic = ({
  code,
  reason,
}: {
  code: string;
  reason: string;
}): RuntimeConnectionDiagnostic => {
  const detail = reason.trim();
  return {
    code: code.toLowerCase().replaceAll("_", "-"),
    message: detail
      ? `Marimo connection closed: ${detail}`
      : "The Marimo runtime connection closed.",
    hint: code === "KERNEL_DISCONNECTED"
      ? "Reload the view after the Marimo server is available."
      : "Fix the notebook startup failure in Marimo, then reload the view.",
  };
};

export const cellDeliveryPhase = ({
  runtimeReady,
  bindingPresent,
  hasCell,
  hasDiagnostic,
  timedOut,
}: {
  runtimeReady: boolean;
  bindingPresent: boolean;
  hasCell: boolean;
  hasDiagnostic: boolean;
  timedOut: boolean;
}): CellDeliveryPhase => {
  if (hasCell) {
    return "received";
  }
  if (
    runtimeReady &&
    bindingPresent &&
    !hasDiagnostic
  ) {
    return timedOut ? "timed-out" : "waiting";
  }
  return "missing";
};

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
