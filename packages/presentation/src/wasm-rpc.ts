import { retry } from "./retry.ts";

export const WASM_PROJECTION_NAMESPACE = "_marimo_studio_wasm";

const RPC_TIMEOUT = "RPC request timed out.";
const RPC_RETRY_DELAYS = [250, 750] as const;

export const isWasmRpcTimeout = (cause: unknown): boolean =>
  cause instanceof Error && cause.message === RPC_TIMEOUT;

export const retryWasmRpc = <T>(operation: () => Promise<T>, signal?: AbortSignal): Promise<T> =>
  retry({
    operation,
    delays: RPC_RETRY_DELAYS,
    retryWhen: isWasmRpcTimeout,
    signal,
  });

export const awaitWasmStartup = <T>(startup: Promise<T>): Promise<T> => {
  const ignoreWorkerDeadline = (event: PromiseRejectionEvent) => {
    // The worker keeps processing startSession after rpc-anywhere's transport
    // deadline. Studio's initialization promise owns the terminal deadline.
    if (isWasmRpcTimeout(event.reason)) {
      event.preventDefault();
    }
  };
  globalThis.addEventListener("unhandledrejection", ignoreWorkerDeadline);
  return startup.finally(() => {
    globalThis.removeEventListener("unhandledrejection", ignoreWorkerDeadline);
  });
};
