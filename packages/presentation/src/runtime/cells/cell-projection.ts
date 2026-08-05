import { outputIsLoading, outputIsStale } from "@marimo-studio/marimo-frontend/cells";

import type { ProjectionDiagnostic } from "../../runtime-config/index";
import type { RuntimeCell } from "../runtime-cell";

import {
  type CellDeliveryPhase,
  cellDeliveryPhase,
  type CellPhase,
  cellPhase,
} from "../cell-state";
import { filterCellLogs } from "./cell-output-policy";

export type CellDiagnostic = Pick<ProjectionDiagnostic, "code" | "message" | "hint">;

export interface CellProjection {
  consoleOutputs: RuntimeCell["consoleOutputs"];
  delivery: CellDeliveryPhase;
  diagnostic?: CellDiagnostic;
  disabled: boolean;
  hasOutput: boolean;
  loading: boolean;
  outputMime?: string;
  outputMimes: string;
  stale: boolean;
  state: CellPhase;
}

interface CellProjectionInput {
  alias: string;
  bindingPresent: boolean;
  cell: RuntimeCell | undefined;
  diagnostic?: CellDiagnostic;
  deliveryTimedOut: boolean;
  runtimeReady: boolean;
  showCellLogs: boolean;
}

const ERROR_MIMES = new Set(["application/vnd.marimo+error", "application/vnd.marimo+traceback"]);

const outputMessagesFor = (
  cell: RuntimeCell | undefined,
  consoleOutputs: RuntimeCell["consoleOutputs"],
): RuntimeCell["consoleOutputs"] => {
  if (!cell) {
    return [];
  }
  if (!cell.output) {
    return consoleOutputs;
  }
  return [...consoleOutputs, cell.output];
};

const executionDiagnostic = ({
  alias,
  disabled,
  failed,
  hasOutput,
}: {
  alias: string;
  disabled: boolean;
  failed: boolean;
  hasOutput: boolean;
}): CellDiagnostic | undefined => {
  if (disabled && !hasOutput) {
    return {
      code: "cell-disabled",
      message: `Cell ${JSON.stringify(alias)} is disabled.`,
      hint: "Enable the cell in Marimo or remove this projection.",
    };
  }
  if (failed) {
    return {
      code: "cell-execution-error",
      message: `Cell ${JSON.stringify(alias)} failed during execution.`,
      hint: "Fix the cell error in Marimo, then run it again.",
    };
  }
  return undefined;
};

const deliveryDiagnostic = (
  alias: string,
  delivery: CellDeliveryPhase,
): CellDiagnostic | undefined => {
  if (delivery !== "timed-out") {
    return undefined;
  }
  return {
    code: "runtime-cell-not-received",
    message: `Cell ${JSON.stringify(alias)} did not reach the browser.`,
    hint: "Wait for the notebook to settle, then reload the view.",
  };
};

const DELIVERY_PHASES: Partial<Record<CellDeliveryPhase, CellPhase>> = {
  waiting: "loading",
  "timed-out": "error",
};

const resolvedCellPhase = (
  delivery: CellDeliveryPhase,
  input: Parameters<typeof cellPhase>[0],
): CellPhase => DELIVERY_PHASES[delivery] ?? cellPhase(input);

export const projectCell = ({
  alias,
  bindingPresent,
  cell,
  diagnostic,
  deliveryTimedOut,
  runtimeReady,
  showCellLogs,
}: CellProjectionInput): CellProjection => {
  const stale = cell ? outputIsStale(cell, cell.edited) : false;
  const disabled = cell
    ? cell.config.disabled === true || cell.status === "disabled-transitively"
    : false;
  const consoleOutputs = filterCellLogs(cell?.consoleOutputs ?? [], showCellLogs);
  const awaitingFirstRun =
    cell !== undefined &&
    cell.lastRunStartTimestamp === null &&
    cell.output === null &&
    consoleOutputs.length === 0 &&
    cell.status === "idle";
  const loading = cell ? !disabled && (outputIsLoading(cell.status) || awaitingFirstRun) : false;
  const outputMessages = outputMessagesFor(cell, consoleOutputs);
  const visibleOutputs = outputMessages.filter(
    (output) => output.data !== "" && output.data !== null,
  );
  const hasOutput = visibleOutputs.length > 0;
  const authoritativeOutputs = hasOutput ? visibleOutputs : outputMessages;
  const outputMimes = authoritativeOutputs.map((output) => output.mimetype);
  const failed =
    cell?.errored === true ||
    outputMessages.some(
      (output) => output.channel === "marimo-error" || ERROR_MIMES.has(output.mimetype),
    );
  const delivery = cellDeliveryPhase({
    runtimeReady,
    bindingPresent,
    hasCell: cell !== undefined,
    hasDiagnostic: diagnostic !== undefined,
    timedOut: deliveryTimedOut,
  });
  const effectiveDiagnostic =
    diagnostic ??
    deliveryDiagnostic(alias, delivery) ??
    executionDiagnostic({ alias, disabled, failed, hasOutput });
  const state = resolvedCellPhase(delivery, {
    runtimeReady,
    hasCell: cell !== undefined,
    loading,
    disabled,
    hasOutput,
    failed,
    stale,
  });

  return {
    consoleOutputs,
    delivery,
    diagnostic: effectiveDiagnostic,
    disabled,
    hasOutput,
    loading,
    outputMime: outputMimes.at(-1),
    outputMimes: outputMimes.join(" "),
    stale,
    state,
  };
};
