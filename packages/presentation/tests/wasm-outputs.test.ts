import { describe, expect, test, vi } from "vite-plus/test";

import type { OutputResponseReconciler } from "../src/outputs/reader";
import type { FunctionResult } from "../src/values/wasm";

import { createWasmOutputReader, createWasmOutputRequest } from "../src/outputs/wasm";
import { projectionWireRequest } from "../src/projections/identity";
import { commitRuntimeConfig } from "../src/runtime-config";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures";

const rendered = {
  found: true,
  status: { code: "ok", message: null },
  return_value: {
    outputs: {
      df: {
        ownerCellId: "__marimo_studio_output_df",
        mimetype: "text/html",
        data: "<table></table>",
        timestamp: 1,
        resetUiObjectIds: [],
      },
    },
    errors: {},
  },
} satisfies FunctionResult;

describe("WebAssembly output reads", () => {
  test("dispatches a native render at most once after a worker failure", async () => {
    const df = projectionRequest("df", "output");
    commitRuntimeConfig(projectionRuntimeConfig([df]));
    const failure = new Error("RPC request timed out.");
    const invoke = vi.fn(async () => Promise.reject(failure));
    const authorize = vi.fn(async () => {});
    const request = createWasmOutputRequest("preview-a", invoke, authorize);
    const projection = {
      revision: "presentation-revision",
      projections: [df],
      activeProjections: [df],
    };

    await expect(request(projection)).rejects.toBe(failure);

    expect(authorize).toHaveBeenCalledWith(projection, undefined);
    expect(invoke).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledWith({
      namespace: "_marimo_studio_wasm",
      functionName: "render_values",
      args: {
        revision: "presentation-revision",
        projections: [projectionWireRequest(df)],
        active_projections: [projectionWireRequest(df)],
        consumer_id: "preview-a",
        max_output_bytes: 1_000_000,
      },
    });
  });

  test("waits for initialization, serializes renders, and drops aborted queued work", async () => {
    const df = projectionRequest("df", "output");
    const figure = projectionRequest("figure", "output");
    const staleRequest = projectionRequest("stale", "output");
    commitRuntimeConfig(projectionRuntimeConfig([df, figure, staleRequest]));
    let initialize = () => {};
    const initialized = new Promise<void>((resolve) => {
      initialize = resolve;
    });
    let completeFirst: (value: FunctionResult) => void = () => {};
    const firstResponse = new Promise<FunctionResult>((resolve) => {
      completeFirst = resolve;
    });
    const request = vi
      .fn()
      .mockImplementationOnce(() => firstResponse)
      .mockResolvedValueOnce(rendered);
    const reconcile = vi.fn<OutputResponseReconciler>((response) => response);
    const reader = createWasmOutputReader(() => initialized, request, reconcile);
    const firstProjection = {
      revision: "presentation-revision",
      projections: [df],
      activeProjections: [df, figure],
    };
    const secondProjection = {
      revision: "presentation-revision",
      projections: [figure],
      activeProjections: [df, figure],
    };
    const staleProjection = {
      revision: "presentation-revision",
      projections: [staleRequest],
      activeProjections: [df, staleRequest],
    };
    const controller = new AbortController();
    const first = reader(firstProjection);
    const second = reader(secondProjection);
    const stale = reader(staleProjection, controller.signal);

    await Promise.resolve();
    expect(request).not.toHaveBeenCalled();
    initialize();
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(request).toHaveBeenCalledWith(firstProjection);
    controller.abort();
    await expect(stale).rejects.toMatchObject({ name: "AbortError" });
    completeFirst(rendered);

    await expect(first).resolves.toEqual(rendered.return_value);
    await expect(second).resolves.toEqual(rendered.return_value);
    expect(request).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenNthCalledWith(2, secondProjection);
    expect(reconcile).toHaveBeenCalledTimes(2);
  });

  test("discards a native render after its caller stops waiting", async () => {
    const df = projectionRequest("df", "output");
    commitRuntimeConfig(projectionRuntimeConfig([df]));
    let complete: (value: FunctionResult) => void = () => {};
    const response = new Promise<FunctionResult>((resolve) => {
      complete = resolve;
    });
    const request = vi.fn(async () => response);
    const reconcile = vi.fn<OutputResponseReconciler>((result) => result);
    const reader = createWasmOutputReader(async () => {}, request, reconcile);
    const controller = new AbortController();
    const projection = {
      revision: "presentation-revision",
      projections: [df],
      activeProjections: [df],
    };

    const reading = reader(projection, controller.signal);
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    controller.abort();
    await expect(reading).rejects.toMatchObject({ name: "AbortError" });
    complete(rendered);
    await Promise.resolve();
    await Promise.resolve();

    expect(reconcile).not.toHaveBeenCalled();
  });
});
