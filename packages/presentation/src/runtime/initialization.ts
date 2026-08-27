export const WASM_STARTUP_TIMEOUT_MS = 60_000;

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
      (cause: unknown) => settle(() => reject(cause)),
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

export const createWasmInitialization = (): WasmInitialization => {
  const controller = new AbortController();
  return {
    signal: controller.signal,
    wait: (workerInitialized, notebookInitialized, timeout) =>
      waitForWasmInitialization(controller, workerInitialized, notebookInitialized, timeout),
    abort: (cause) => controller.abort(cause),
  };
};
