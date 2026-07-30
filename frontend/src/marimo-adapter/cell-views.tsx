import {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
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
  flattenTopLevelNotebookCells,
  useCellActions,
  useNotebook,
} from "@marimo-team/frontend/unstable_internal/core/cells/cells";
import { RuntimeState } from "@marimo-team/frontend/unstable_internal/core/kernel/RuntimeState";
import type { SessionId } from "@marimo-team/frontend/unstable_internal/core/kernel/session";
import { useRequestClient } from "@marimo-team/frontend/unstable_internal/core/network/requests";
import { WebSocketState } from "@marimo-team/frontend/unstable_internal/core/websocket/types";
import { useMarimoKernelConnection } from "@marimo-team/frontend/unstable_internal/core/websocket/useMarimoKernelConnection";

import {
  getCellHosts,
  type MarimoCellElement,
  setCellHostState,
  subscribeCellHosts,
} from "../cell-host";
import {
  cellBindingKey,
  type CellIndex,
  indexCells,
  resolveCellBinding,
} from "../cell-bindings";
import { setRuntimeConnectionState } from "../readiness";
import {
  type CellBindingConfig,
  getRuntimeConfig,
  type ProjectionDiagnostic,
  subscribeRuntimeConfig,
  type ValueBindingConfig,
} from "../runtime-config";
import {
  applyValues,
  markValueError,
  markValuePending,
  readValuesWithRetry,
  ValueRequestError,
} from "../value-bindings";
import {
  CELL_DELIVERY_TIMEOUT_MS,
  cellDeliveryPhase,
  cellPhase,
  runtimeConnectionDiagnostic,
} from "./cell-state";
import { valueCellPhase } from "./value-cell-state";

type RuntimeCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

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

const useCellHosts = () => {
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
  onSubmitStdin: (
    cell: RuntimeCell,
    text: string,
    outputIndex: number,
  ) => void;
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

const RuntimeValueCell = ({
  selectors,
  cell,
  connectionState,
  runtimeReady,
  sessionId,
}: {
  selectors: string[];
  cell: RuntimeCell | undefined;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  sessionId: string;
}) => {
  const cellId = cell?.id ?? null;
  const hasCell = cell !== undefined;
  const [deliveryTimedOut, setDeliveryTimedOut] = useState(false);
  useEffect(() => {
    setDeliveryTimedOut(false);
    if (!runtimeReady || hasCell) {
      return;
    }
    const timeout = setTimeout(
      () => setDeliveryTimedOut(true),
      CELL_DELIVERY_TIMEOUT_MS,
    );
    return () => clearTimeout(timeout);
  }, [cellId, hasCell, runtimeReady]);

  const version = cell?.lastRunStartTimestamp ?? null;
  const status = cell?.status ?? "missing";
  const errored = cell?.errored ?? false;
  const stale = cell ? outputIsStale(cell, cell.edited) : false;
  const phase = valueCellPhase({
    runtimeReady,
    hasCell,
    disabled: cell?.config.disabled ?? false,
    status,
    version,
    errored,
    stale,
    deliveryTimedOut,
  });

  useLayoutEffect(() => {
    if (phase === "loading" || phase === "stale") {
      selectors.forEach(markValuePending);
      return;
    }
    if (phase === "error") {
      selectors.forEach((selector) => {
        markValueError(
          selector,
          !hasCell && deliveryTimedOut
            ? {
              code: "runtime-cell-not-received",
              message: `The cell backing ${
                JSON.stringify(selector)
              } did not reach the browser.`,
              hint: "Wait for the notebook to settle, then reload the view.",
            }
            : {
              code: "defining-cell-error",
              message: `The cell backing ${
                JSON.stringify(selector)
              } is unavailable.`,
            },
        );
      });
    }
  }, [deliveryTimedOut, hasCell, phase, selectors]);

  useEffect(() => {
    if (
      connectionState !== WebSocketState.OPEN ||
      phase !== "ready"
    ) {
      return;
    }

    selectors.forEach(markValuePending);
    const controller = new AbortController();
    let current = true;
    void readValuesWithRetry(sessionId, selectors, controller.signal)
      .then((response) => {
        if (!current) {
          return;
        }
        applyValues(response.values);
        selectors.forEach((selector) => {
          const error = response.errors[selector];
          if (error) {
            markValueError(selector, error);
            return;
          }
          if (!Object.hasOwn(response.values, selector)) {
            markValueError(selector, {
              code: "missing-value-response",
              message: `The kernel response omitted ${
                JSON.stringify(selector)
              }.`,
            });
          }
        });
      })
      .catch((error: unknown) => {
        if (
          !current ||
          (error instanceof DOMException && error.name === "AbortError")
        ) {
          return;
        }
        selectors.forEach((selector) => {
          markValueError(selector, {
            code: error instanceof ValueRequestError
              ? error.code
              : "value-request-failed",
            message: error instanceof Error ? error.message : String(error),
          });
        });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [
    cellId,
    connectionState,
    phase,
    sessionId,
    selectors,
    version,
  ]);

  return null;
};

const RuntimeValues = ({
  bindings,
  cells,
  connectionState,
  runtimeReady,
  sessionId,
}: {
  bindings: Record<string, ValueBindingConfig>;
  cells: CellIndex<RuntimeCell>;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  sessionId: string;
}) => {
  const groups = useMemo(() => {
    const byCell = new Map<
      string,
      { binding: CellBindingConfig; selectors: Set<string> }
    >();
    Object.entries(bindings).forEach(([selector, binding]) => {
      const key = cellBindingKey(binding.cell);
      const group = byCell.get(key) ?? {
        binding: binding.cell,
        selectors: new Set<string>(),
      };
      group.selectors.add(selector);
      byCell.set(key, group);
    });
    return Array.from(byCell, ([key, group]) => ({
      key,
      binding: group.binding,
      selectors: Array.from(group.selectors).sort(),
    }));
  }, [bindings]);

  return groups.map(({ key, binding, selectors }) => (
    <RuntimeValueCell
      key={key}
      selectors={selectors}
      cell={resolveCellBinding(binding, cells)}
      connectionState={connectionState}
      runtimeReady={runtimeReady}
      sessionId={sessionId}
    />
  ));
};

const ConfiguredRuntimeValues = (
  props: Omit<Parameters<typeof RuntimeValues>[0], "bindings">,
) => {
  const config = useSyncExternalStore(
    subscribeRuntimeConfig,
    getRuntimeConfig,
    getRuntimeConfig,
  );
  return <RuntimeValues {...props} bindings={config.valueBindings} />;
};

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

const RuntimeCellPortals = ({
  cells,
  hosts,
  runtimeReady,
  onSubmitStdin,
}: {
  cells: CellIndex<RuntimeCell>;
  hosts: readonly MarimoCellElement[];
  runtimeReady: boolean;
  onSubmitStdin: CellViewProps["onSubmitStdin"];
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

export const RuntimeCellViews = ({
  sessionId,
}: {
  sessionId: SessionId;
}) => {
  const { setCells, setStdinResponse } = useCellActions();
  const { sendComponentValues, sendStdin } = useRequestClient();
  const notebook = useNotebook();
  const hosts = useCellHosts();

  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => RuntimeState.INSTANCE.stop();
  }, [sendComponentValues]);

  (globalThis as typeof globalThis & Window).__MARIMO_STUDIO_SESSION_ID__ =
    sessionId;
  const { connection } = useMarimoKernelConnection({
    autoInstantiate: true,
    setCells,
    sessionId,
  });

  useEffect(() => {
    if (connection.state === WebSocketState.OPEN) {
      setRuntimeConnectionState("ready");
      return;
    }
    if (connection.state === WebSocketState.CLOSED) {
      setRuntimeConnectionState(
        "error",
        runtimeConnectionDiagnostic(connection),
      );
      return;
    }
    setRuntimeConnectionState("connecting");
  }, [connection]);

  const cells = useMemo(
    () => flattenTopLevelNotebookCells(notebook),
    [notebook],
  );
  const cellIndex = useMemo(
    () => indexCells(cells),
    [cells],
  );
  const runtimeReady = connection.state === WebSocketState.OPEN;
  const submitStdin = useCallback(
    (cell: RuntimeCell, text: string, outputIndex: number) => {
      setStdinResponse({
        cellId: cell.id,
        response: text,
        outputIndex,
      });
      void sendStdin({ text });
    },
    [sendStdin, setStdinResponse],
  );

  return (
    <Fragment>
      <ConfiguredRuntimeValues
        cells={cellIndex}
        connectionState={connection.state}
        runtimeReady={runtimeReady}
        sessionId={sessionId}
      />
      <RuntimeCellPortals
        cells={cellIndex}
        hosts={hosts}
        runtimeReady={runtimeReady}
        onSubmitStdin={submitStdin}
      />
    </Fragment>
  );
};
