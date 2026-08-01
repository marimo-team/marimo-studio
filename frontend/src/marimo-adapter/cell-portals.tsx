import {
  memo,
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";

import { cellDomProps } from "@marimo-team/frontend/unstable_internal/components/editor/common";
import { OutputArea } from "@marimo-team/frontend/unstable_internal/components/editor/Output";
import { ConsoleOutput } from "@marimo-team/frontend/unstable_internal/components/editor/output/console/ConsoleOutput";
import {
  outputIsLoading,
  outputIsStale,
} from "@marimo-team/frontend/unstable_internal/core/cells/cell";

import {
  getCellHosts,
  type MarimoCellElement,
  setCellHostState,
  subscribeCellHosts,
} from "../cell-host";
import {
  cellBindingKey,
  type CellIndex,
  resolveCellBinding,
} from "../cell-bindings";
import {
  getRuntimeConfig,
  type ProjectionDiagnostic,
  subscribeRuntimeConfig,
} from "../runtime-config";
import {
  CELL_DELIVERY_TIMEOUT_MS,
  cellDeliveryPhase,
  cellPhase,
} from "./cell-state";
import type { RuntimeCell } from "./runtime-cell";

export type SubmitStdin = (
  cell: RuntimeCell,
  text: string,
  outputIndex: number,
) => void;

const hostIds = new WeakMap<MarimoCellElement, number>();
let nextHostId = 0;

const getHostId = (host: MarimoCellElement): number => {
  const existing = hostIds.get(host);
  if (existing !== undefined) {
    return existing;
  }
  const created = nextHostId++;
  hostIds.set(host, created);
  return created;
};

export const useCellHosts = () => {
  return useSyncExternalStore(subscribeCellHosts, getCellHosts, getCellHosts);
};

type CellDiagnostic = Pick<
  ProjectionDiagnostic,
  "code" | "message" | "hint"
>;

const CellNotFound = ({
  alias,
  developer,
  diagnostic,
}: {
  alias: string;
  developer: boolean;
  diagnostic?: CellDiagnostic;
}) => {
  const message = developer
    ? diagnostic?.message ?? `Cell ${JSON.stringify(alias)} is unavailable.`
    : "This section is unavailable.";
  return (
    <div className="marimo-cell-diagnostic" role="status">
      <strong>{message}</strong>
      {developer && diagnostic?.hint ? <span>{diagnostic.hint}</span> : null}
    </div>
  );
};

const CellUnavailable = ({ alias }: { alias: string }) => {
  return (
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{alias}</code> is disabled in the notebook graph.
    </div>
  );
};

interface CellViewProps {
  host: MarimoCellElement;
  cell: RuntimeCell | undefined;
  bindingPresent: boolean;
  bindingKey?: string;
  developer: boolean;
  diagnostic?: CellDiagnostic;
  runtimeReady: boolean;
  onSubmitStdin: SubmitStdin;
}

const CellView = memo(function CellView({
  host,
  cell,
  bindingPresent,
  bindingKey,
  developer,
  diagnostic,
  runtimeReady,
  onSubmitStdin,
}: CellViewProps) {
  const [deliveryTimedOut, setDeliveryTimedOut] = useState(false);
  useEffect(() => {
    setDeliveryTimedOut(false);
    if (
      !runtimeReady ||
      !bindingPresent ||
      cell !== undefined ||
      diagnostic !== undefined
    ) {
      return;
    }
    const timeout = setTimeout(
      () => setDeliveryTimedOut(true),
      CELL_DELIVERY_TIMEOUT_MS,
    );
    return () => clearTimeout(timeout);
  }, [bindingKey, bindingPresent, cell, diagnostic, runtimeReady]);

  const stale = cell ? outputIsStale(cell, cell.edited) : false;
  const disabled = cell
    ? cell.config.disabled === true || cell.status === "disabled-transitively"
    : false;
  const awaitingFirstRun = cell !== undefined &&
    cell.lastRunStartTimestamp === null &&
    cell.output === null &&
    cell.consoleOutputs.length === 0 &&
    cell.status === "idle";
  const loading = cell
    ? !disabled && (outputIsLoading(cell.status) || awaitingFirstRun)
    : false;
  const outputMessages = cell
    ? [...cell.consoleOutputs, ...(cell.output ? [cell.output] : [])]
    : [];
  const visibleOutputMessages = outputMessages.filter((output) =>
    output.data !== "" && output.data !== null
  );
  const hasOutput = visibleOutputMessages.length > 0;
  const authoritativeOutputs = visibleOutputMessages.length > 0
    ? visibleOutputMessages
    : outputMessages;
  const outputMimes = authoritativeOutputs.map((output) => output.mimetype);
  const outputMimesValue = outputMimes.join(" ");
  const outputMime = outputMimes.at(-1);
  const failed = cell?.errored === true ||
    outputMessages.some((output) =>
      output.channel === "marimo-error" ||
      output.mimetype === "application/vnd.marimo+error" ||
      output.mimetype === "application/vnd.marimo+traceback"
    );
  const delivery = cellDeliveryPhase({
    runtimeReady,
    bindingPresent,
    hasCell: cell !== undefined,
    hasDiagnostic: diagnostic !== undefined,
    timedOut: deliveryTimedOut,
  });
  const deliveryDiagnostic: CellDiagnostic | undefined =
    delivery === "timed-out"
      ? {
        code: "runtime-cell-not-received",
        message: `Cell ${
          JSON.stringify(host.cellName)
        } did not reach the browser.`,
        hint: "Wait for the notebook to settle, then reload the view.",
      }
      : undefined;
  const cellDiagnostic: CellDiagnostic | undefined = disabled && !hasOutput
    ? {
      code: "cell-disabled",
      message: `Cell ${JSON.stringify(host.cellName)} is disabled.`,
      hint: "Enable the cell in Marimo or remove this projection.",
    }
    : failed
    ? {
      code: "cell-execution-error",
      message: `Cell ${JSON.stringify(host.cellName)} failed during execution.`,
      hint: "Fix the cell error in Marimo, then run it again.",
    }
    : undefined;
  const effectiveDiagnostic = diagnostic ?? deliveryDiagnostic ??
    cellDiagnostic;
  const state = delivery === "waiting"
    ? "loading"
    : delivery === "timed-out"
    ? "error"
    : cellPhase({
      runtimeReady,
      hasCell: cell !== undefined,
      loading,
      disabled,
      hasOutput,
      failed,
      stale,
    });

  useLayoutEffect(() => {
    if (cell) {
      host.dataset.runtimeCellId = cell.id;
    } else {
      delete host.dataset.runtimeCellId;
    }
    if (outputMime) {
      host.dataset.outputMime = outputMime;
      host.dataset.outputMimes = outputMimesValue;
    } else {
      delete host.dataset.outputMime;
      delete host.dataset.outputMimes;
    }
    if (effectiveDiagnostic) {
      host.dataset.marimoDiagnosticCode = effectiveDiagnostic.code;
      host.dataset.marimoDiagnosticMessage = effectiveDiagnostic.message;
      host.dataset.marimoDiagnosticHint = effectiveDiagnostic.hint;
    } else {
      delete host.dataset.marimoDiagnosticCode;
      delete host.dataset.marimoDiagnosticMessage;
      delete host.dataset.marimoDiagnosticHint;
    }
    setCellHostState(host, state, {
      alias: host.cellName,
      runtimeId: cell?.id,
      outputMime,
      code: effectiveDiagnostic?.code,
      message: effectiveDiagnostic?.message,
      hint: effectiveDiagnostic?.hint,
    });
  }, [
    cell,
    effectiveDiagnostic,
    host,
    outputMime,
    outputMimesValue,
    state,
  ]);

  if (!cell) {
    if (!runtimeReady || delivery === "waiting") {
      return null;
    }
    return createPortal(
      <CellNotFound
        alias={host.cellName}
        developer={developer}
        diagnostic={effectiveDiagnostic}
      />,
      host,
    );
  }
  if (loading && !hasOutput) {
    return null;
  }
  if (disabled && !hasOutput) {
    return createPortal(<CellUnavailable alias={host.cellName} />, host);
  }

  return createPortal(
    <div
      className="marimo"
      data-marimo-cell-output=""
      {...cellDomProps(cell.id, cell.name)}
    >
      <ConsoleOutput
        cellId={cell.id}
        cellName="_"
        consoleOutputs={cell.consoleOutputs}
        stale={(cell.status === "queued" || cell.edited || cell.staleInputs) &&
          !cell.interrupted}
        interrupted={cell.interrupted}
        debuggerActive={cell.debuggerActive}
        onSubmitDebugger={(text, outputIndex) =>
          onSubmitStdin(cell, text, outputIndex)}
      />
      <OutputArea
        allowExpand={false}
        output={cell.output}
        cellId={cell.id}
        stale={stale}
        loading={loading}
      />
    </div>,
    host,
  );
});

const DuplicateCellView = ({ host }: { host: MarimoCellElement }) => {
  useLayoutEffect(() => {
    const message = `Cell ${JSON.stringify(host.cellName)} is mounted twice.`;
    const hint = "Keep one host for each projected cell.";
    host.dataset.marimoDiagnosticCode = "duplicate-cell-host";
    host.dataset.marimoDiagnosticMessage = message;
    host.dataset.marimoDiagnosticHint = hint;
    setCellHostState(host, "error", {
      alias: host.cellName,
      code: "duplicate-cell-host",
      message,
      hint,
    });
    return () => {
      delete host.dataset.marimoDiagnosticCode;
      delete host.dataset.marimoDiagnosticMessage;
      delete host.dataset.marimoDiagnosticHint;
    };
  }, [host]);
  return createPortal(
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{host.cellName}</code> is already mounted.
    </div>,
    host,
  );
};

export const RuntimeCellPortals = ({
  cells,
  hosts,
  runtimeReady,
  onSubmitStdin,
}: {
  cells: CellIndex<RuntimeCell>;
  hosts: readonly MarimoCellElement[];
  runtimeReady: boolean;
  onSubmitStdin: SubmitStdin;
}) => {
  const config = useSyncExternalStore(
    subscribeRuntimeConfig,
    getRuntimeConfig,
    getRuntimeConfig,
  );
  const diagnostics = new Map(
    config.diagnostics
      .filter((diagnostic) => diagnostic.projection === "cell")
      .map((diagnostic) => [diagnostic.target, diagnostic]),
  );
  const developer = config.dev || config.mode === "edit";
  const primaryHosts = new Map<string, MarimoCellElement>();
  hosts.forEach((host) => {
    if (!primaryHosts.has(host.cellName)) {
      primaryHosts.set(host.cellName, host);
    }
  });
  return hosts.map((host) => {
    const binding = config.cellBindings[host.cellName];
    return primaryHosts.get(host.cellName) !== host
      ? <DuplicateCellView key={getHostId(host)} host={host} />
      : (
        <CellView
          key={getHostId(host)}
          host={host}
          cell={resolveCellBinding(binding, cells)}
          bindingPresent={binding !== undefined}
          bindingKey={binding && cellBindingKey(binding)}
          developer={developer}
          diagnostic={diagnostics.get(host.cellName)}
          runtimeReady={runtimeReady}
          onSubmitStdin={onSubmitStdin}
        />
      );
  });
};
