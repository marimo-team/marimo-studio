import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  ownPresentationWasmWorker,
  startPresentationWasmSession,
  terminatePresentationWasmWorker,
} from "../src/wasm-worker-owner.ts";

afterEach(() => {
  terminatePresentationWasmWorker();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("the presentation owns and terminates one WebAssembly worker", () => {
  const terminate = vi.fn();
  const worker = { terminate };
  const rejectedTerminate = vi.fn();

  expect(ownPresentationWasmWorker(worker)).toBe(worker);
  expect(() => ownPresentationWasmWorker({ terminate: rejectedTerminate })).toThrow(
    "A presentation WebAssembly worker is already active",
  );
  expect(rejectedTerminate).toHaveBeenCalledOnce();

  terminatePresentationWasmWorker();
  terminatePresentationWasmWorker();
  expect(terminate).toHaveBeenCalledOnce();
});

test("a late worker RPC timeout remains owned after terminal startup", async () => {
  vi.useFakeTimers();
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

  startPresentationWasmSession(
    () =>
      new Promise((_resolve, reject) => {
        setTimeout(() => reject(new Error("RPC request timed out.")), 125_000);
      }),
  );
  await vi.advanceTimersByTimeAsync(125_000);

  expect(consoleError).not.toHaveBeenCalled();

  const failure = new Error("worker failed");
  startPresentationWasmSession(() => Promise.reject(failure));
  await Promise.resolve();
  await Promise.resolve();
  expect(consoleError).toHaveBeenCalledWith(
    "The presentation WebAssembly session failed to start.",
    failure,
  );
});
