export type CellPhase = "connecting" | "missing" | "loading" | "error" | "stale" | "ready";

export type RuntimeConnectionState = "NOT_STARTED" | "CONNECTING" | "OPEN" | "CLOSING" | "CLOSED";

export type RuntimeConnection =
  | { state: Exclude<RuntimeConnectionState, "CLOSED"> }
  | { state: "CLOSED"; code: string; reason: string };

export type RuntimeInitialization =
  | { state: "connecting" | "ready" }
  | { state: "error"; error: unknown };

export type CellDeliveryPhase = "received" | "waiting" | "timed-out" | "missing";

export const CELL_DELIVERY_TIMEOUT_MS = 10_000;

export interface DeliveryTimeout {
  identity: string | null | undefined;
}

export const deliveryTimedOut = (
  waiting: boolean,
  identity: string | null | undefined,
  timeout: DeliveryTimeout | null,
): boolean => waiting && timeout !== null && Object.is(timeout.identity, identity);

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
    hint:
      code === "KERNEL_DISCONNECTED"
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
  if (runtimeReady && bindingPresent && !hasDiagnostic) {
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
