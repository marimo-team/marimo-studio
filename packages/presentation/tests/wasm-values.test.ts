import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import {
  createWasmValueReader,
  type FunctionRequest,
  type FunctionResult,
  waitForWasmValueBridge,
} from "../src/values/wasm";

const response = (value: number): FunctionResult => ({
  found: true,
  status: { code: "ok", message: null },
  return_value: { values: { total: value }, errors: {} },
});

describe("WebAssembly value reads", () => {
  afterEach(() => vi.useRealTimers());

  test("waits for the notebook value bridge", async () => {
    vi.useFakeTimers();
    const request = vi
      .fn<FunctionRequest>()
      .mockResolvedValueOnce({
        found: false,
        status: { code: "ok", message: null },
        return_value: null,
      })
      .mockResolvedValueOnce(response(0));
    const waiting = waitForWasmValueBridge(request, new AbortController().signal);

    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(250);

    await expect(waiting).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledTimes(2);
  });

  test("waits for runtime initialization", async () => {
    let initialize = () => {};
    const initialized = new Promise<void>((resolve) => {
      initialize = resolve;
    });
    const request = vi.fn(async () => response(3));
    const reading = createWasmValueReader(
      () => initialized,
      request,
    )({
      revision: "presentation-revision",
      selectors: ["total"],
    });

    await Promise.resolve();
    expect(request).not.toHaveBeenCalled();
    initialize();

    await expect(reading).resolves.toEqual({ values: { total: 3 }, errors: {} });
  });

  test("serializes calls while one native request is pending", async () => {
    let complete: (value: FunctionResult) => void = () => {};
    const firstResponse = new Promise<FunctionResult>((resolve) => {
      complete = resolve;
    });
    const request = vi
      .fn<FunctionRequest>()
      .mockImplementationOnce(() => firstResponse)
      .mockResolvedValueOnce(response(2));
    const reader = createWasmValueReader(async () => {}, request);

    const valueRequest = { revision: "presentation-revision", selectors: ["total"] };
    const first = reader(valueRequest);
    const second = reader(valueRequest);
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));

    complete(response(1));
    await expect(first).resolves.toEqual({ values: { total: 1 }, errors: {} });
    await expect(second).resolves.toEqual({ values: { total: 2 }, errors: {} });
    expect(request).toHaveBeenCalledTimes(2);
  });

  test("drops an aborted read before it reaches the native queue", async () => {
    let complete: (value: FunctionResult) => void = () => {};
    const firstResponse = new Promise<FunctionResult>((resolve) => {
      complete = resolve;
    });
    const request = vi.fn<FunctionRequest>(() => firstResponse);
    const reader = createWasmValueReader(async () => {}, request);
    const controller = new AbortController();

    const first = reader({ revision: "presentation-revision", selectors: ["first"] });
    const stale = reader(
      { revision: "presentation-revision", selectors: ["stale"] },
      controller.signal,
    );
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    controller.abort();

    await expect(stale).rejects.toMatchObject({ name: "AbortError" });
    complete(response(1));
    await expect(first).resolves.toEqual({ values: { total: 1 }, errors: {} });
    await Promise.resolve();
    expect(request).toHaveBeenCalledTimes(1);
  });
});
