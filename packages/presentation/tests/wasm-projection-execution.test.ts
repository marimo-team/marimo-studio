import { expect, test, vi } from "vite-plus/test";

import type { WasmRuntimeData } from "../src/runtime/wasm-config";

import { createWasmProjectionExecutor } from "../src/runtime/wasm-projection-execution";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures";

const first = projectionRequest("first", "value");
const second = projectionRequest("second", "value");
const base = projectionRuntimeConfig([first, second]);
const config = {
  ...base,
  projectionTargets: {
    ...base.projectionTargets,
    variables: {
      ...base.projectionTargets.variables,
      first: {
        status: "ready" as const,
        producer: "cell:v1:first",
        dependencyClosure: ["cell:v1:source", "cell:v1:first"],
      },
    },
  },
  runtimeBindings: {
    cellRefs: {
      "cell:v1:source": "source-cell",
      "cell:v1:first": "first-cell",
      "cell:v1:second": "second-cell",
    },
  },
};
const data: WasmRuntimeData = {
  code: "",
  filename: "notebook.py",
  version: "1",
  executionCells: [
    { id: "bootstrap-cell", code: "register_bridge()" },
    { id: "source-cell", code: "source = 1" },
    { id: "first-cell", code: "first = source + 1" },
    { id: "second-cell", code: "second = 2" },
    { id: "unrelated-cell", code: "raise RuntimeError()" },
  ],
  bootstrapCellId: "bootstrap-cell",
};

test("executes each authorized dependency closure once", async () => {
  const executeCells = vi.fn(async () => {});
  const executor = createWasmProjectionExecutor(executeCells, async () => {});

  await executor.prepareRequests(config, data, [first]);
  await executor.prepareRequests(config, data, [first]);
  await executor.prepareRequests(config, data, [second]);

  expect(executeCells).toHaveBeenCalledTimes(2);
  expect(executeCells).toHaveBeenNthCalledWith(1, [
    { id: "source-cell", code: "source = 1" },
    { id: "first-cell", code: "first = source + 1" },
  ]);
  expect(executeCells).toHaveBeenNthCalledWith(2, [{ id: "second-cell", code: "second = 2" }]);
});

test("drops an unmounted projection before its execution slot starts", async () => {
  let finishFirst = () => {};
  const firstExecution = new Promise<void>((resolve) => {
    finishFirst = resolve;
  });
  const executeCells = vi
    .fn<(cells: readonly { id: string; code: string }[]) => Promise<void>>()
    .mockImplementationOnce(() => firstExecution)
    .mockResolvedValueOnce();
  const executor = createWasmProjectionExecutor(executeCells, async () => {});
  const controller = new AbortController();

  const running = executor.prepareRequests(config, data, [first]);
  const unmounted = executor.prepareRequests(config, data, [second], controller.signal);
  const current = executor.prepareRequests(config, data, [second]);
  await vi.waitFor(() => expect(executeCells).toHaveBeenCalledOnce());
  controller.abort();

  await expect(unmounted).rejects.toMatchObject({ name: "AbortError" });
  finishFirst();
  await running;
  await current;
  expect(executeCells).toHaveBeenCalledTimes(2);
  expect(executeCells).toHaveBeenLastCalledWith([{ id: "second-cell", code: "second = 2" }]);
});

test("rejects an unauthorized request before executing notebook code", async () => {
  const executeCells = vi.fn(async () => {});
  const executor = createWasmProjectionExecutor(executeCells, async () => {});

  await expect(
    executor.prepareRequests(config, data, [{ ...first, siteId: "site:value:forged" }]),
  ).rejects.toThrow("unavailable");
  expect(executeCells).not.toHaveBeenCalled();
});
