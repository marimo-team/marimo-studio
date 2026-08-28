import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import { projectionWireRequest } from "../src/projections/identity";
import { commitRuntimeConfig } from "../src/runtime-config";
import {
  createWasmValueReader,
  type FunctionRequest,
  type FunctionResult,
  waitForWasmProjectionBridge,
} from "../src/values/wasm";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures";

const jsonValue = (value: number) => ({
  codec: "json-v1" as const,
  fingerprint: `sha256:${String(value).repeat(64)}`,
  value,
});

const response = (value: number): FunctionResult => ({
  found: true,
  status: { code: "ok", message: null },
  return_value: { values: { total: jsonValue(value) }, errors: {} },
});

describe("WebAssembly value reads", () => {
  afterEach(() => vi.useRealTimers());

  test("waits for the notebook value bridge", async () => {
    vi.useFakeTimers();
    const request = vi
      .fn<(signal: AbortSignal) => Promise<FunctionResult>>()
      .mockResolvedValueOnce({
        found: false,
        status: { code: "ok", message: null },
        return_value: null,
      })
      .mockResolvedValueOnce(response(0));
    const waiting = waitForWasmProjectionBridge(request, new AbortController().signal);

    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(250);

    await expect(waiting).resolves.toBeUndefined();
    expect(request).toHaveBeenCalledTimes(2);
  });

  test("waits for runtime initialization", async () => {
    const requestProjection = projectionRequest("total", "value");
    commitRuntimeConfig(projectionRuntimeConfig([requestProjection]));
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
      projections: [requestProjection],
      activeProjections: [requestProjection],
    });

    await Promise.resolve();
    expect(request).not.toHaveBeenCalled();
    initialize();

    await expect(reading).resolves.toEqual({ values: { total: jsonValue(3) }, errors: {} });
    expect(request).toHaveBeenCalledWith(
      {
        revision: "presentation-revision",
        projections: [projectionWireRequest(requestProjection)],
        activeProjections: [projectionWireRequest(requestProjection)],
      },
      undefined,
    );
  });

  test("serializes calls while one native request is pending", async () => {
    const requestProjection = projectionRequest("total", "value");
    commitRuntimeConfig(projectionRuntimeConfig([requestProjection]));
    let complete: (value: FunctionResult) => void = () => {};
    const firstResponse = new Promise<FunctionResult>((resolve) => {
      complete = resolve;
    });
    const request = vi
      .fn<FunctionRequest>()
      .mockImplementationOnce(() => firstResponse)
      .mockResolvedValueOnce(response(2));
    const reader = createWasmValueReader(async () => {}, request);

    const valueRequest = {
      revision: "presentation-revision",
      projections: [requestProjection],
      activeProjections: [requestProjection],
    };
    const first = reader(valueRequest);
    const second = reader(valueRequest);
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));

    complete(response(1));
    await expect(first).resolves.toEqual({ values: { total: jsonValue(1) }, errors: {} });
    await expect(second).resolves.toEqual({ values: { total: jsonValue(2) }, errors: {} });
    expect(request).toHaveBeenCalledTimes(2);
  });

  test("drops an aborted read before it reaches the native queue", async () => {
    const firstProjection = projectionRequest("first", "value");
    const staleProjection = projectionRequest("stale", "value");
    commitRuntimeConfig(projectionRuntimeConfig([firstProjection, staleProjection]));
    let complete: (value: FunctionResult) => void = () => {};
    const firstResponse = new Promise<FunctionResult>((resolve) => {
      complete = resolve;
    });
    const request = vi.fn<FunctionRequest>(() => firstResponse);
    const reader = createWasmValueReader(async () => {}, request);
    const controller = new AbortController();

    const first = reader({
      revision: "presentation-revision",
      projections: [firstProjection],
      activeProjections: [firstProjection],
    });
    const stale = reader(
      {
        revision: "presentation-revision",
        projections: [staleProjection],
        activeProjections: [staleProjection],
      },
      controller.signal,
    );
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    controller.abort();

    await expect(stale).rejects.toMatchObject({ name: "AbortError" });
    complete(response(1));
    await expect(first).resolves.toEqual({ values: { total: jsonValue(1) }, errors: {} });
    await Promise.resolve();
    expect(request).toHaveBeenCalledTimes(1);
  });
});
