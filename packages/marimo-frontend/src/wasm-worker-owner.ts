interface OwnedWasmWorker {
  terminate(): void;
}

let active: OwnedWasmWorker | undefined;

export const ownPresentationWasmWorker = <Worker extends OwnedWasmWorker>(
  worker: Worker,
): Worker => {
  if (active !== undefined) {
    worker.terminate();
    throw new Error("A presentation WebAssembly worker is already active");
  }
  active = worker;
  return worker;
};

export const terminatePresentationWasmWorker = (): void => {
  const worker = active;
  active = undefined;
  worker?.terminate();
};

export const startPresentationWasmSession = (start: () => Promise<void>): void => {
  void start().catch((cause: unknown) => {
    if (cause instanceof Error && cause.message === "RPC request timed out.") {
      return;
    }
    console.error("The presentation WebAssembly session failed to start.", cause);
  });
};
