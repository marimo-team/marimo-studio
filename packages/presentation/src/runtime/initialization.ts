export const WASM_STARTUP_TIMEOUT_MS = 60_000;

export const waitForWasmInitialization = (
  workerInitialized: Promise<void>,
  notebookInitialized: (signal: AbortSignal) => Promise<void>,
  timeout = WASM_STARTUP_TIMEOUT_MS,
): Promise<void> =>
  new Promise((resolve, reject) => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      controller.abort();
      reject(new Error(`WebAssembly runtime did not start within ${timeout / 1000} seconds.`));
    }, timeout);
    workerInitialized
      .then(() => notebookInitialized(controller.signal))
      .then(
        () => {
          clearTimeout(timer);
          resolve();
        },
        (cause: unknown) => {
          clearTimeout(timer);
          reject(cause);
        },
      );
  });
