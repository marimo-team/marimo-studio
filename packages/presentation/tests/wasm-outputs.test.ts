import { describe, expect, test, vi } from "vite-plus/test";

import type { OutputResponseReconciler } from "../src/outputs/reader";
import type { FunctionResult } from "../src/values/wasm";

import { createWasmOutputReader, createWasmOutputRequest } from "../src/outputs/wasm";
import {
  createProjectionSpecSynchronizer,
  type WasmProjectionSpecs,
} from "../src/runtime/wasm-config";

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
  test("retries an unchanged projection update after synchronization fails", async () => {
    const initial = { valueSpecs: {}, outputSpecs: {} };
    const projected = {
      valueSpecs: {},
      outputSpecs: { df: ["df", []] },
    } satisfies WasmProjectionSpecs;
    const failure = new Error("RPC request timed out.");
    const apply = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(undefined);
    const synchronize = createProjectionSpecSynchronizer(initial, apply);

    await expect(synchronize(projected)).rejects.toBe(failure);
    await expect(synchronize(projected)).resolves.toBeUndefined();
    expect(apply).toHaveBeenCalledTimes(2);
    expect(apply).toHaveBeenLastCalledWith(projected);
  });

  test("dispatches a native render at most once after a worker failure", async () => {
    const failure = new Error("RPC request timed out.");
    const invoke = vi.fn(async () => Promise.reject(failure));
    const request = createWasmOutputRequest("preview-a", invoke);

    await expect(
      request({
        revision: "presentation-revision",
        selectors: ["df"],
        activeSelectors: ["df"],
      }),
    ).rejects.toBe(failure);

    expect(invoke).toHaveBeenCalledOnce();
    expect(invoke).toHaveBeenCalledWith({
      namespace: "_marimo_studio",
      functionName: "render_values",
      args: {
        selectors: ["df"],
        active_selectors: ["df"],
        consumer_id: "preview-a",
        max_output_bytes: 1_000_000,
      },
    });
  });

  test("waits for initialization, serializes renders, and drops aborted queued work", async () => {
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
      selectors: ["df"],
      activeSelectors: ["df", "figure"],
    };
    const secondProjection = {
      revision: "presentation-revision",
      selectors: ["figure"],
      activeSelectors: ["df", "figure"],
    };
    const staleProjection = {
      revision: "presentation-revision",
      selectors: ["stale"],
      activeSelectors: ["df"],
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
      selectors: ["df"],
      activeSelectors: ["df"],
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
