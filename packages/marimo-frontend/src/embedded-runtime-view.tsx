import type { ReactNode } from "react";

import { useCallback, useEffect, useMemo, useState } from "react";

import type {
  EmbeddedConnection,
  EmbeddedFunction,
  EmbeddedInitialization,
  EmbeddedRuntimeCell,
  EmbeddedRuntimeView,
} from "./embedded-runtime.tsx";
import type { SessionId } from "./session-bootstrap.ts";
import type { useCellActions } from "./upstream/cells.ts";
import type { useRequestClient } from "./upstream/runtime.ts";

import { resolveEmbeddedCellId } from "./embedded-runtime-core.ts";

export type EmbeddedCellActions = Pick<
  ReturnType<typeof useCellActions>,
  "setCells" | "setStdinResponse"
>;

export type EmbeddedRequestClient = Pick<
  ReturnType<typeof useRequestClient>,
  "sendComponentValues" | "sendStdin"
>;

interface EmbeddedConnectionInput {
  readonly autoInstantiate: boolean;
  readonly sessionId: SessionId;
  readonly setCells: EmbeddedCellActions["setCells"];
}

export interface EmbeddedRuntimeKernel<Notebook> {
  readonly invoke: EmbeddedFunction;
  flattenCells(notebook: Notebook): EmbeddedRuntimeCell[];
  startRuntime(sendComponentValues: EmbeddedRequestClient["sendComponentValues"]): void;
  stopRuntime(): void;
  useCellActions(): EmbeddedCellActions;
  useConnection(input: EmbeddedConnectionInput): EmbeddedConnection;
  useNotebook(): Notebook;
  useRequestClient(): EmbeddedRequestClient;
}

const useInitialization = (initialized: Promise<void>): EmbeddedInitialization => {
  const [state, setState] = useState<EmbeddedInitialization>({ state: "connecting" });

  useEffect(() => {
    let active = true;
    initialized.then(
      () => {
        if (active) {
          setState({ state: "ready" });
        }
      },
      (cause: unknown) => {
        if (active) {
          setState({ state: "error", error: cause });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [initialized]);

  return state;
};

export const EmbeddedRuntimeViewComponent = <Notebook,>({
  autoInstantiate,
  initialized,
  kernel,
  render,
  sessionId,
}: {
  autoInstantiate: boolean;
  initialized: Promise<void>;
  kernel: EmbeddedRuntimeKernel<Notebook>;
  render: (runtime: EmbeddedRuntimeView) => ReactNode;
  sessionId: SessionId;
}) => {
  const { setCells, setStdinResponse } = kernel.useCellActions();
  const { sendComponentValues, sendStdin } = kernel.useRequestClient();
  const notebook = kernel.useNotebook();
  const initialization = useInitialization(initialized);

  useEffect(() => {
    kernel.startRuntime(sendComponentValues);
    return () => kernel.stopRuntime();
  }, [kernel, sendComponentValues]);

  const connection = kernel.useConnection({ autoInstantiate, setCells, sessionId });
  const cells = useMemo(() => kernel.flattenCells(notebook), [kernel, notebook]);
  const submitStdin = useCallback(
    (cellId: string, text: string, outputIndex: number) => {
      const resolvedCellId = resolveEmbeddedCellId(cells, cellId);
      setStdinResponse({
        cellId: resolvedCellId,
        response: text,
        outputIndex,
      });
      void sendStdin({ text });
    },
    [cells, sendStdin, setStdinResponse],
  );

  return render({
    cells,
    connection,
    initialization,
    initialized,
    invoke: kernel.invoke,
    sessionId,
    submitStdin,
  });
};
