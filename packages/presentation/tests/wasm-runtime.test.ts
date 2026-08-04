import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { waitForWasmInitialization } from "../src/runtime/initialization";

describe("WebAssembly runtime initialization", () => {
  afterEach(() => vi.useRealTimers());

  it("reports a worker that never starts", async () => {
    vi.useFakeTimers();
    const waiting = waitForWasmInitialization(
      new Promise<void>(() => {}),
      () => Promise.resolve(),
      10_000,
    );
    const rejected = expect(waiting).rejects.toThrow(
      "WebAssembly runtime did not start within 10 seconds.",
    );

    await vi.advanceTimersByTimeAsync(10_000);
    await rejected;
  });

  it("reports a notebook that never instantiates", async () => {
    vi.useFakeTimers();
    const waiting = waitForWasmInitialization(
      Promise.resolve(),
      () => new Promise<void>(() => {}),
      10_000,
    );
    const rejected = expect(waiting).rejects.toThrow(
      "WebAssembly runtime did not start within 10 seconds.",
    );

    await vi.advanceTimersByTimeAsync(10_000);
    await rejected;
  });
});
