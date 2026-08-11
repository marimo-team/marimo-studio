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
import { useCallback, useEffect, useMemo, useState } from "react";

import type { SubmitStdin } from "../runtime-cell";

import { indexCells } from "../../cells/bindings";
import { errorMessage } from "../../errors";
import { setRuntimeConnectionState } from "../../rendered-view-observer";
import { runtimeConnectionDiagnostic } from "../cell-state";
import { useCellHosts } from "../cells/use-cell-hosts";

type Initialization = { state: "connecting" | "ready" } | { state: "error"; error: unknown };

const useInitialization = (initialized: Promise<void>): Initialization => {
  const [state, setState] = useState<Initialization>({ state: "connecting" });

  useEffect(() => {
    let active = true;
    initialized.then(
      () => {
        if (active) {
          setState({ state: "ready" });
        }
      },
      (error: unknown) => {
        if (active) {
          setState({ state: "error", error });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [initialized]);

  return state;
};

export const useRuntimeCells = ({
  initialized,
  sessionId,
}: {
  initialized: Promise<void>;
  sessionId: SessionId;
}) => {
  const { setCells, setStdinResponse } = useCellActions();
  const { sendComponentValues, sendStdin } = useRequestClient();
  const notebook = useNotebook();
  const hosts = useCellHosts();
  const initialization = useInitialization(initialized);

  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => RuntimeState.INSTANCE.stop();
  }, [sendComponentValues]);

  const { connection } = useMarimoKernelConnection({
    autoInstantiate: true,
    setCells,
    sessionId,
  });

  useEffect(() => {
    if (initialization.state === "error") {
      setRuntimeConnectionState("error", {
        code: "runtime-initialization-failed",
        message: errorMessage(initialization.error),
        hint: "Review the browser console, then reload after the runtime dependency is available.",
      });
      return;
    }
    if (connection.state === WebSocketState.OPEN && initialization.state === "ready") {
      setRuntimeConnectionState("ready");
      return;
    }
    if (connection.state === WebSocketState.CLOSED) {
      setRuntimeConnectionState("error", runtimeConnectionDiagnostic(connection));
      return;
    }
    setRuntimeConnectionState("connecting");
  }, [connection, initialization]);

  const cells = useMemo(() => flattenTopLevelNotebookCells(notebook), [notebook]);
  const cellIndex = useMemo(() => indexCells(cells), [cells]);
  const runtimeReady = connection.state === WebSocketState.OPEN && initialization.state === "ready";
  const submitStdin = useCallback<SubmitStdin>(
    (cell, text, outputIndex) => {
      setStdinResponse({ cellId: cell.id, response: text, outputIndex });
      void sendStdin({ text });
    },
    [sendStdin, setStdinResponse],
  );

  return {
    cells: cellIndex,
    connectionState: connection.state,
    hosts,
    runtimeReady,
    submitStdin,
  };
};
