import {
  flattenTopLevelNotebookCells,
  RuntimeState,
  useCellActions,
  useNotebook,
} from "@marimo-studio/marimo-frontend/cells";
import {
  type SessionId,
  useMarimoKernelConnection,
  useRequestClient,
  WebSocketState,
} from "@marimo-studio/marimo-frontend/runtime";
import { Fragment, useCallback, useEffect, useMemo } from "react";

import { indexCells } from "../cells/bindings";
import { setRuntimeConnectionState } from "../readiness";
import { RuntimeCellPortals, type SubmitStdin, useCellHosts } from "./cell-portals";
import { runtimeConnectionDiagnostic } from "./cell-state";
import { ConfiguredRuntimeValues } from "./value-views";

export const RuntimeCellViews = ({ sessionId }: { sessionId: SessionId }) => {
  const { setCells, setStdinResponse } = useCellActions();
  const { sendComponentValues, sendStdin } = useRequestClient();
  const notebook = useNotebook();
  const hosts = useCellHosts();

  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => RuntimeState.INSTANCE.stop();
  }, [sendComponentValues]);

  (globalThis as typeof globalThis & Window).__MARIMO_STUDIO_SESSION_ID__ = sessionId;
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
      setRuntimeConnectionState("error", runtimeConnectionDiagnostic(connection));
      return;
    }
    setRuntimeConnectionState("connecting");
  }, [connection]);

  const cells = useMemo(() => flattenTopLevelNotebookCells(notebook), [notebook]);
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
