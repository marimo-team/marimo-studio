import { useCallback, useEffect, useMemo } from "react";

import type { RuntimeCell, SubmitStdin } from "../runtime-cell";

import { indexCells } from "../../cells/index";
import { errorMessage } from "../../errors";
import { setRuntimeConnectionState } from "../../rendered-view-observer";
import {
  type RuntimeConnection,
  runtimeConnectionDiagnostic,
  type RuntimeInitialization,
} from "../cell-state";
import { useCellHosts } from "../cells/use-cell-hosts";

export interface RuntimeCellSource {
  readonly cells: RuntimeCell[];
  readonly connection: RuntimeConnection;
  readonly initialization: RuntimeInitialization;
  readonly submitStdin: (cellId: string, text: string, outputIndex: number) => void;
}

export const useRuntimeCells = ({
  cells,
  connection,
  initialization,
  submitStdin: submitEmbeddedStdin,
}: RuntimeCellSource) => {
  const hosts = useCellHosts();

  useEffect(() => {
    if (initialization.state === "error") {
      setRuntimeConnectionState("error", {
        code: "runtime-initialization-failed",
        message: errorMessage(initialization.error),
        hint: "Review the browser console, then reload after the runtime dependency is available.",
      });
      return;
    }
    if (connection.state === "OPEN" && initialization.state === "ready") {
      setRuntimeConnectionState("ready");
      return;
    }
    if (connection.state === "CLOSED") {
      setRuntimeConnectionState("error", runtimeConnectionDiagnostic(connection));
      return;
    }
    setRuntimeConnectionState("connecting");
  }, [connection, initialization]);

  const cellIndex = useMemo(() => indexCells(cells), [cells]);
  const runtimeReady = connection.state === "OPEN" && initialization.state === "ready";
  const submitStdin = useCallback<SubmitStdin>(
    (cell, text, outputIndex) => {
      submitEmbeddedStdin(cell.id, text, outputIndex);
    },
    [submitEmbeddedStdin],
  );

  return {
    cells: cellIndex,
    connectionState: connection.state,
    hosts,
    runtimeReady,
    submitStdin,
  };
};
