import { Fragment, useCallback, useEffect, useMemo } from "react";

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

import { indexCells } from "../cell-bindings";
import { setRuntimeConnectionState } from "../readiness";
import {
  RuntimeCellPortals,
  type SubmitStdin,
  useCellHosts,
} from "./cell-portals";
import { runtimeConnectionDiagnostic } from "./cell-state";
import { ConfiguredRuntimeValues } from "./value-views";

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
  const cellIndex = useMemo(() => indexCells(cells), [cells]);
  const runtimeReady = connection.state === WebSocketState.OPEN;
  const submitStdin = useCallback<SubmitStdin>(
    (cell, text, outputIndex) => {
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
