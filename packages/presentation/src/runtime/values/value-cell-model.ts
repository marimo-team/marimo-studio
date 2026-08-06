import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import type { RuntimeCell } from "../runtime-cell";

import { type ValueCellPhase, valueCellPhase } from "../value-cell-state";

export interface ValueCellModel {
  cellId: string | null;
  failure?: "defining-cell-error" | "runtime-cell-not-received";
  hasCell: boolean;
  phase: ValueCellPhase;
  version: number | null;
}

type ValueCellFailure = NonNullable<ValueCellModel["failure"]>;

const FAILURE_DETAILS: Readonly<Record<ValueCellFailure, (selector: string) => ValueReadError>> = {
  "defining-cell-error": (selector) => ({
    code: "defining-cell-error",
    message: `The cell backing ${JSON.stringify(selector)} is unavailable.`,
  }),
  "runtime-cell-not-received": (selector) => ({
    code: "runtime-cell-not-received",
    message: `The cell backing ${JSON.stringify(selector)} did not reach the browser.`,
    hint: "Wait for the notebook to settle, then reload the view.",
  }),
};

export const valueCellFailure = (failure: ValueCellFailure, selector: string): ValueReadError =>
  FAILURE_DETAILS[failure](selector);

export const valueCellModel = (
  cell: RuntimeCell | undefined,
  runtimeReady: boolean,
  deliveryTimedOut: boolean,
): ValueCellModel => {
  const cellId = cell?.id ?? null;
  const hasCell = cell !== undefined;
  const version = cell?.lastRunStartTimestamp ?? null;
  const phase = valueCellPhase({
    runtimeReady,
    hasCell,
    disabled: cell?.config.disabled ?? false,
    status: cell?.status ?? "missing",
    version,
    errored: cell?.errored ?? false,
    stale: (cell?.staleInputs ?? false) && !(cell?.interrupted ?? false),
    deliveryTimedOut,
  });

  if (phase !== "error") {
    return { cellId, hasCell, phase, version };
  }
  if (!hasCell && deliveryTimedOut) {
    return {
      cellId,
      hasCell,
      phase,
      version,
      failure: "runtime-cell-not-received",
    };
  }
  return {
    cellId,
    hasCell,
    phase,
    version,
    failure: "defining-cell-error",
  };
};
