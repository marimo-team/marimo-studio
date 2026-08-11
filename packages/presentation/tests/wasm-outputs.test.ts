import { reconcileProjectedOutput } from "@marimo-studio/marimo-frontend/projected-output";
import { beforeEach, describe, expect, test, vi } from "vite-plus/test";

import { createWasmOutputReader, createWasmOutputRequest } from "../src/outputs/wasm";
import { createProjectionSpecSynchronizer } from "../src/runtime/wasm-config";

vi.mock("@marimo-studio/marimo-frontend/projected-output", () => ({
  reconcileProjectedOutput: vi.fn(),
}));

beforeEach(() => vi.clearAllMocks());

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
};

describe("WebAssembly output reads", () => {
  test("retries an unchanged projection update after synchronization fails", async () => {
    const initial = { valueSpecs: {}, outputSpecs: {} };
    const projected = {
      valueSpecs: {},
      outputSpecs: { df: ["df", []] as [string, []] },
    };
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
    let completeFirst = (_value: unknown) => {};
    const firstResponse = new Promise<unknown>((resolve) => {
      completeFirst = resolve;
    });
    const request = vi
      .fn()
      .mockImplementationOnce(() => firstResponse)
      .mockResolvedValueOnce(rendered);
    const reader = createWasmOutputReader(initialized, request);
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
  });

  test("discards a native render after its caller stops waiting", async () => {
    let complete = (_value: unknown) => {};
    const response = new Promise<unknown>((resolve) => {
      complete = resolve;
    });
    const request = vi.fn(async () => response);
    const reader = createWasmOutputReader(Promise.resolve(), request);
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

    expect(reconcileProjectedOutput).not.toHaveBeenCalled();
  });
});
