import {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
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
import { setRuntimeConnectionState } from "../readiness";
import {
  getRuntimeCells,
  getRuntimeConfig,
  subscribeRuntimeCells,
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
import { cellPhase } from "./cell-state";
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

const CellNotFound = ({ alias }: { alias: string }) => {
  return (
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{alias}</code> is unavailable in this runtime.
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
  runtimeReady,
  onSubmitStdin,
}: CellViewProps) {
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
  const state = cellPhase({
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
    setCellHostState(host, state, {
      alias: host.cellName,
      runtimeId: cell?.id,
      outputMime,
    });
  }, [cell, host, outputMime, outputMimesValue, state]);

  if (!cell) {
    if (!runtimeReady) {
      return null;
    }
    return createPortal(<CellNotFound alias={host.cellName} />, host);
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
  const version = cell?.lastRunStartTimestamp ?? null;
  const status = cell?.status ?? "missing";
  const errored = cell?.errored ?? false;
  const hasCell = cell !== undefined;
  const stale = cell ? outputIsStale(cell, cell.edited) : false;
  const phase = valueCellPhase({
    runtimeReady,
    hasCell,
    disabled: cell?.config.disabled ?? false,
    status,
    version,
    errored,
    stale,
  });

  useLayoutEffect(() => {
    if (phase === "loading" || phase === "stale") {
      selectors.forEach(markValuePending);
      return;
    }
    if (phase === "error") {
      selectors.forEach((selector) => {
        markValueError(selector, {
          code: "defining-cell-error",
          message: `The cell backing ${
            JSON.stringify(selector)
          } is unavailable.`,
        });
      });
    }
  }, [phase, selectors]);

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
  cellsById,
  connectionState,
  runtimeReady,
  sessionId,
}: {
  bindings: Record<string, ValueBindingConfig>;
  cellsById: Map<string, RuntimeCell>;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  sessionId: string;
}) => {
  const groups = useMemo(() => {
    const byCell = new Map<string, Set<string>>();
    Object.entries(bindings).forEach(([selector, binding]) => {
      const selectors = byCell.get(binding.cellId) ?? new Set<string>();
      selectors.add(selector);
      byCell.set(binding.cellId, selectors);
    });
    return Array.from(byCell, ([cellId, selectors]) => ({
      cellId,
      selectors: Array.from(selectors).sort(),
    }));
  }, [bindings]);

  return groups.map(({ cellId, selectors }) => (
    <RuntimeValueCell
      key={cellId}
      selectors={selectors}
      cell={cellsById.get(cellId)}
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
    setCellHostState(host, "error", {
      alias: host.cellName,
      code: "duplicate-cell-host",
    });
  }, [host]);
  return createPortal(
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{host.cellName}</code> is already mounted.
    </div>,
    host,
  );
};

const RuntimeCellPortals = ({
  cellsById,
  hosts,
  runtimeReady,
  onSubmitStdin,
}: {
  cellsById: Map<string, RuntimeCell>;
  hosts: readonly MarimoCellElement[];
  runtimeReady: boolean;
  onSubmitStdin: CellViewProps["onSubmitStdin"];
}) => {
  const runtimeCells = useSyncExternalStore(
    subscribeRuntimeCells,
    getRuntimeCells,
    getRuntimeCells,
  );
  const primaryHosts = new Map<string, MarimoCellElement>();
  hosts.forEach((host) => {
    if (!primaryHosts.has(host.cellName)) {
      primaryHosts.set(host.cellName, host);
    }
  });
  return hosts.map((host) =>
    primaryHosts.get(host.cellName) !== host
      ? <DuplicateCellView key={getHostId(host)} host={host} />
      : (
        <CellView
          key={getHostId(host)}
          host={host}
          cell={cellsById.get(runtimeCells[host.cellName])}
          runtimeReady={runtimeReady}
          onSubmitStdin={onSubmitStdin}
        />
      )
  );
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
      setRuntimeConnectionState("error");
      return;
    }
    setRuntimeConnectionState("connecting");
  }, [connection.state]);

  const cells = useMemo(
    () => flattenTopLevelNotebookCells(notebook),
    [notebook],
  );
  const cellsById: Map<string, RuntimeCell> = useMemo(
    () => new Map(cells.map((cell) => [cell.id, cell])),
    [cells],
  );
  const runtimeReady = connection.state === WebSocketState.OPEN &&
    cells.length > 0;
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
        cellsById={cellsById}
        connectionState={connection.state}
        runtimeReady={runtimeReady}
        sessionId={sessionId}
      />
      <RuntimeCellPortals
        cellsById={cellsById}
        hosts={hosts}
        runtimeReady={runtimeReady}
        onSubmitStdin={submitStdin}
      />
    </Fragment>
  );
};
