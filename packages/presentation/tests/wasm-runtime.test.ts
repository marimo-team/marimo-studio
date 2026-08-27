import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import type { RuntimeInvoke } from "../src/runtime/runtime.tsx";
import type { FunctionResult } from "../src/values/wasm.ts";

import { createWasmInitialization } from "../src/runtime/initialization";
import { createWasmQueryWriter } from "../src/runtime/wasm-query.ts";

const deferred = () => {
  let resolve = () => {};
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

describe("WebAssembly runtime initialization", () => {
  afterEach(() => vi.useRealTimers());

  it("reports a worker that never starts", async () => {
    vi.useFakeTimers();
    const worker = deferred();
    const notebookInitialized = vi.fn(async () => {});
    const initialization = createWasmInitialization();
    const waiting = initialization.wait(worker.promise, notebookInitialized, 10_000);
    const rejected = expect(waiting).rejects.toThrow(
      "WebAssembly runtime did not start within 10 seconds.",
    );

    await vi.advanceTimersByTimeAsync(10_000);
    await rejected;
    expect(initialization.signal.aborted).toBe(true);

    worker.resolve();
    await worker.promise;
    await Promise.resolve();
    expect(notebookInitialized).not.toHaveBeenCalled();
  });

  it("reports a notebook that never instantiates", async () => {
    vi.useFakeTimers();
    const initialization = createWasmInitialization();
    const waiting = initialization.wait(
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

  it("does not initialize a worker that resolves after runtime disposal", async () => {
    const worker = deferred();
    const notebookInitialized = vi.fn(async () => {});
    const initialization = createWasmInitialization();
    const waiting = initialization.wait(worker.promise, notebookInitialized);
    const disposed = new DOMException("The runtime was disposed.", "AbortError");
    const rejected = expect(waiting).rejects.toThrow("The runtime was disposed.");

    initialization.abort(disposed);
    await rejected;
    worker.resolve();
    await worker.promise;
    await Promise.resolve();

    expect(notebookInitialized).not.toHaveBeenCalled();
  });
});

describe("WebAssembly query synchronization", () => {
  afterEach(() => vi.useRealTimers());

  it("reuses a generation for retries and coalesces queued queries", async () => {
    vi.useFakeTimers();
    const requests: Array<{ generation: number; query: unknown }> = [];
    const invoke = vi.fn<RuntimeInvoke>(async (request) => {
      // SAFETY: The query writer owns this request and emits this exact args shape.
      const args = request.args as { generation: number; query: unknown };
      requests.push(args);
      if (requests.length === 1) {
        throw new Error("RPC request timed out.");
      }
      return {
        found: true,
        status: { code: "ok", message: null },
        return_value: { generation: args.generation, applied: true },
      } satisfies FunctionResult;
    });
    const owner = new AbortController();
    const writer = createWasmQueryWriter(owner.signal);

    const first = writer.write(invoke, "?region=emea");
    const superseded = writer.write(invoke, "?region=apac");
    const latest = writer.write(invoke, "?region=americas");
    await vi.advanceTimersByTimeAsync(250);
    await Promise.all([first, superseded, latest]);

    expect(requests).toEqual([
      { generation: 1, query: { region: "emea" } },
      { generation: 1, query: { region: "emea" } },
      { generation: 3, query: { region: "americas" } },
    ]);
    writer.dispose();
  });

  it("stops retrying when the runtime is disposed", async () => {
    let rejectInvoke = (_error: Error) => {};
    const invoke = vi.fn<RuntimeInvoke>(
      () =>
        new Promise((_resolve, reject) => {
          rejectInvoke = reject;
        }),
    );
    const owner = new AbortController();
    const writer = createWasmQueryWriter(owner.signal);
    const updating = writer.write(invoke, "?region=emea");
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledOnce());

    owner.abort(new DOMException("The runtime was disposed.", "AbortError"));
    writer.dispose();
    rejectInvoke(new Error("RPC request timed out."));

    await expect(updating).rejects.toMatchObject({ name: "AbortError" });
    expect(invoke).toHaveBeenCalledOnce();
  });
});
