import { notebookQueryValues } from "@marimo-studio/protocol/query";
import { z } from "zod";

import type { RuntimeInvoke } from "./runtime";

import { functionResultSchema } from "../values/wasm";
import { retryWasmRpc, WASM_PROJECTION_NAMESPACE } from "../wasm-rpc";

const acknowledgementSchema = z.strictObject({
  generation: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  applied: z.boolean(),
});

const synchronize = async (
  invoke: RuntimeInvoke,
  query: string,
  generation: number,
  signal: AbortSignal,
): Promise<void> => {
  const result = functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: WASM_PROJECTION_NAMESPACE,
          functionName: "sync_query",
          args: { query: notebookQueryValues(query), generation },
        }),
      signal,
    ),
  );
  if (!result.found || result.status.code !== "ok") {
    throw new Error(result.status.message ?? "The notebook query could not be synchronized.");
  }
  const acknowledgement = acknowledgementSchema.parse(result.return_value);
  if (!acknowledgement.applied || acknowledgement.generation !== generation) {
    throw new Error("A newer notebook query superseded this update.");
  }
};

interface QueryWaiter {
  readonly resolve: () => void;
  readonly reject: (error: Error) => void;
}

interface PendingQueryUpdate {
  readonly invoke: RuntimeInvoke;
  readonly query: string;
  readonly generation: number;
  readonly waiters: QueryWaiter[];
}

export const createWasmQueryWriter = (signal: AbortSignal) => {
  let generation = 0;
  let running = false;
  let pending: PendingQueryUpdate | undefined;
  let disposed = false;

  const drain = async (): Promise<void> => {
    if (running || disposed) {
      return;
    }
    running = true;
    try {
      while (!disposed && pending) {
        const update = pending;
        pending = undefined;
        try {
          signal.throwIfAborted();
          await synchronize(update.invoke, update.query, update.generation, signal);
          update.waiters.forEach(({ resolve }) => resolve());
        } catch (error) {
          const failure =
            error instanceof Error || error instanceof DOMException
              ? error
              : new Error(String(error));
          update.waiters.forEach(({ reject }) => reject(failure));
        }
      }
    } finally {
      running = false;
    }
  };

  return {
    write(invoke: RuntimeInvoke, query: string): Promise<void> {
      if (disposed) {
        return Promise.reject(
          signal.reason ?? new DOMException("The runtime was disposed.", "AbortError"),
        );
      }
      const operation = new Promise<void>((resolve, reject) => {
        pending = {
          invoke,
          query,
          generation: ++generation,
          waiters: [...(pending?.waiters ?? []), { resolve, reject }],
        };
      });
      void drain();
      return operation;
    },
    dispose(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      pending?.waiters.forEach(({ reject }) =>
        reject(signal.reason ?? new DOMException("The runtime was disposed.", "AbortError")),
      );
      pending = undefined;
    },
  };
};
