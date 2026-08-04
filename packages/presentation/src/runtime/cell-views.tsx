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
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import type { ValueReader } from "../values/reader";

import { indexCells } from "../cells/bindings";
import { errorMessage } from "../errors";
import { setRuntimeConnectionState } from "../readiness";
import { RuntimeCellPortals, type SubmitStdin, useCellHosts } from "./cell-portals";
import { runtimeConnectionDiagnostic } from "./cell-state";
import { ConfiguredRuntimeValues } from "./value-views";

export const RuntimeCellViews = ({
  exposeSession,
  initialized,
  readValues,
  sessionId,
}: {
  exposeSession: boolean;
  initialized: Promise<void>;
  readValues: ValueReader;
  sessionId: SessionId;
}) => {
  const { setCells, setStdinResponse } = useCellActions();
  const { sendComponentValues, sendStdin } = useRequestClient();
  const notebook = useNotebook();
  const hosts = useCellHosts();
  const [initialization, setInitialization] = useState<
    { state: "connecting" | "ready" } | { state: "error"; error: unknown }
  >({ state: "connecting" });

  useEffect(() => {
    let active = true;
    initialized.then(
      () => {
        if (active) {
          setInitialization({ state: "ready" });
        }
      },
      (error: unknown) => {
        if (active) {
          setInitialization({ state: "error", error });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [initialized]);

  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => RuntimeState.INSTANCE.stop();
  }, [sendComponentValues]);

  if (exposeSession) {
    (globalThis as typeof globalThis & Window).__MARIMO_STUDIO_SESSION_ID__ = sessionId;
  }
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
        readValues={readValues}
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
