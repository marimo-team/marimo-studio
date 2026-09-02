// Browser dependency loading can outlive Marimo's default worker RPC deadline.
// This owner terminates the worker when the complete startup window expires.
export const WASM_STARTUP_TIMEOUT_MS = 120_000;

const waitForWasmInitialization = (
  controller: AbortController,
  workerInitialized: Promise<void>,
  notebookInitialized: (signal: AbortSignal) => Promise<void>,
  timeout = WASM_STARTUP_TIMEOUT_MS,
): Promise<void> => {
  const signal = controller.signal;
  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (complete: () => void): void => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      complete();
    };
    const abort = (): void => {
      const cause =
        signal.reason ?? new DOMException("The WebAssembly runtime was cancelled.", "AbortError");
      settle(() => reject(cause));
    };
    const timer = setTimeout(() => {
      controller.abort(
        new Error(`WebAssembly runtime did not start within ${timeout / 1000} seconds.`),
      );
    }, timeout);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      abort();
      return;
    }
    void (async () => {
      await workerInitialized;
      signal.throwIfAborted();
      await notebookInitialized(signal);
      signal.throwIfAborted();
    })().then(
      () => settle(resolve),
      (cause: unknown) => {
        if (!signal.aborted) {
          controller.abort(cause);
        }
      },
    );
  });
};

export interface WasmInitialization {
  readonly signal: AbortSignal;
  wait(
    workerInitialized: Promise<void>,
    notebookInitialized: (signal: AbortSignal) => Promise<void>,
    timeout?: number,
  ): Promise<void>;
  abort(cause?: unknown): void;
}

export const createWasmInitialization = (
  abortWorker: () => void = () => {},
): WasmInitialization => {
  const controller = new AbortController();
  controller.signal.addEventListener("abort", abortWorker, { once: true });
  return {
    signal: controller.signal,
    wait: (workerInitialized, notebookInitialized, timeout) =>
      waitForWasmInitialization(controller, workerInitialized, notebookInitialized, timeout),
    abort: (cause) => controller.abort(cause),
  };
};
