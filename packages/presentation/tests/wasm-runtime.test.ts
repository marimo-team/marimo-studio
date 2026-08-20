import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import type { RuntimeInvoke } from "../src/runtime/runtime.tsx";
import type { FunctionResult } from "../src/values/wasm.ts";

import { createWasmInitialization } from "../src/runtime/initialization";
import { createObservedDeferred } from "../src/runtime/observed-deferred.ts";
import { createWasmQueryWriter } from "../src/runtime/wasm-query.ts";

vi.stubGlobal("matchMedia", () => ({
  matches: false,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
}));

const deferred = () => {
  let resolve = () => {};
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

describe("WebAssembly runtime initialization", () => {
  afterEach(() => vi.useRealTimers());

  it.each([
    ["early disposal", new DOMException("The runtime was disposed.", "AbortError")],
    ["startup failure", new Error("The WebAssembly projection bridge failed to initialize.")],
  ])("keeps %s observable by a later readiness waiter", async (_case, failure) => {
    const readiness = createObservedDeferred<void>();

    readiness.reject(failure);
    await new Promise((resolve) => setTimeout(resolve, 0));

    await expect(readiness.promise).rejects.toBe(failure);
  });

  it("retains dependency-heavy startup while the worker keeps progressing", async () => {
    vi.useFakeTimers();
    const worker = deferred();
    const notebookInitialized = vi.fn(async () => {});
    const terminateWorker = vi.fn();
    const initialization = createWasmInitialization(terminateWorker);
    const waiting = initialization.wait(worker.promise, notebookInitialized);

    await vi.advanceTimersByTimeAsync(119_999);
    expect(notebookInitialized).not.toHaveBeenCalled();
    worker.resolve();
    await waiting;
    expect(notebookInitialized).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(initialization.signal.aborted).toBe(false);
    expect(notebookInitialized).toHaveBeenCalledOnce();
    expect(terminateWorker).not.toHaveBeenCalled();
  });

  it("terminates in-flight worker startup at the terminal deadline", async () => {
    vi.useFakeTimers();
    const notebook = deferred();
    const terminateWorker = vi.fn();
    const initialization = createWasmInitialization(terminateWorker);
    const waiting = initialization.wait(Promise.resolve(), () => notebook.promise);
    const rejected = expect(waiting).rejects.toThrow(
      "WebAssembly runtime did not start within 120 seconds.",
    );

    await vi.advanceTimersByTimeAsync(120_000);
    await rejected;
    expect(terminateWorker).toHaveBeenCalledOnce();

    notebook.resolve();
    await notebook.promise;
    await Promise.resolve();
    expect(terminateWorker).toHaveBeenCalledOnce();
  });

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
    await writer.dispose();
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
    await writer.dispose();
    rejectInvoke(new Error("RPC request timed out."));

    await expect(updating).rejects.toMatchObject({ name: "AbortError" });
    expect(invoke).toHaveBeenCalledOnce();
  });

  it("settles an active update when its transport does not cooperate with disposal", async () => {
    const invoke = vi.fn<RuntimeInvoke>(() => new Promise(() => {}));
    const owner = new AbortController();
    const writer = createWasmQueryWriter(owner.signal);
    const updating = writer.write(invoke, "?region=emea");
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledOnce());
    let closed = false;
    const disposing = writer.dispose().then(() => {
      closed = true;
    });

    await expect(updating).rejects.toMatchObject({ name: "AbortError" });
    await expect(disposing).resolves.toBeUndefined();
    expect(closed).toBe(true);
    expect(invoke).toHaveBeenCalledOnce();
  });
});

it("waits for the raw WebAssembly query RPC before revision admission", async () => {
  let finishRaw = (_value: null) => {};
  const raw = new Promise<null>((resolve) => {
    finishRaw = resolve;
  });
  const invoke = vi.fn(() => raw);
  const queries = createWasmQueryController(invoke);
  const queryController = new AbortController();

  const querying = queries.update("?mode=stale", queryController.signal);
  const cancelled = expect(querying).rejects.toMatchObject({ name: "AbortError" });
  await vi.waitFor(() => expect(invoke).toHaveBeenCalledOnce());
  queryController.abort(new DOMException("Query superseded", "AbortError"));
  await cancelled;

  let admitted = false;
  const quiesced = queries.quiesce(new AbortController().signal).then(() => {
    admitted = true;
  });
  await Promise.resolve();
  expect(admitted).toBe(false);
  finishRaw(null);
  await quiesced;
  expect(admitted).toBe(true);
});

it("cancels revision admission while retaining the raw WebAssembly query fence", async () => {
  let finishRaw = (_value: null) => {};
  const raw = new Promise<null>((resolve) => {
    finishRaw = resolve;
  });
  const queries = createWasmQueryController(vi.fn(() => raw));
  const queryController = new AbortController();
  const querying = queries.update("?mode=stale", queryController.signal);
  const queryFailure = expect(querying).rejects.toMatchObject({ name: "AbortError" });
  queryController.abort(new DOMException("Query superseded", "AbortError"));
  await queryFailure;
  const revisionController = new AbortController();
  const quiescing = queries.quiesce(revisionController.signal);
  const revisionFailure = expect(quiescing).rejects.toMatchObject({ name: "AbortError" });

  revisionController.abort(new DOMException("Revision cancelled", "AbortError"));
  await revisionFailure;
  let admitted = false;
  const nextRevision = queries.quiesce(new AbortController().signal).then(() => {
    admitted = true;
  });
  await Promise.resolve();
  expect(admitted).toBe(false);
  finishRaw(null);
  await nextRevision;
  expect(admitted).toBe(true);
});

it("fences a timed-out WebAssembly query before revision admission", async () => {
  vi.useFakeTimers();
  try {
    const invoke = vi.fn(async () => {
      throw new Error("RPC request timed out.");
    });
    const queries = createWasmQueryController(invoke);
    const querying = queries.update("?mode=stale", new AbortController().signal);
    const timedOut = expect(querying).rejects.toThrow("RPC request timed out.");

    await vi.advanceTimersByTimeAsync(1_000);
    await timedOut;

    await expect(queries.quiesce(new AbortController().signal)).rejects.toThrow(
      "query completion is uncertain",
    );
    expect(invoke).toHaveBeenCalledTimes(3);
  } finally {
    vi.useRealTimers();
  }
});
