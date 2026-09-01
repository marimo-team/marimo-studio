import type { EmbeddedCellExecutor } from "@marimo-studio/marimo-frontend/embedded-runtime";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import type { RuntimeInvoke } from "./runtime.tsx";
import type { WasmRuntimeData } from "./wasm-config.ts";

import {
  functionResultSchema,
  throwIfWasmAborted,
  waitForWasmCaller,
  waitForWasmProjectionBridge,
} from "../values/wasm.ts";
import { retryWasmRpc, WASM_PROJECTION_NAMESPACE } from "../wasm-rpc.ts";

interface WasmQueryWriter {
  readonly write: (invoke: RuntimeInvoke, query: string) => Promise<void>;
}

interface WasmProjectionStartup {
  readonly authorizeProjections: (
    invoke: RuntimeInvoke,
    config: RuntimeConfig,
    signal?: AbortSignal,
  ) => Promise<void>;
  readonly config: RuntimeConfig;
  readonly data: WasmRuntimeData;
  readonly executeCells: EmbeddedCellExecutor;
  readonly invoke: RuntimeInvoke;
  readonly queryWriter: WasmQueryWriter;
  readonly signal: AbortSignal;
}

const requestProjectionBridge = async (invoke: RuntimeInvoke, signal?: AbortSignal) =>
  functionResultSchema.parse(
    await retryWasmRpc(
      () =>
        invoke({
          namespace: WASM_PROJECTION_NAMESPACE,
          functionName: "projection_bridge_ready",
          args: {},
        }),
      signal,
    ),
  );

export const resolveWasmRuntimeUrl = (
  rootUrl: string,
  documentBaseUrl = globalThis.document.baseURI,
): string => new URL(rootUrl, documentBaseUrl).toString();

export const prepareWasmProjectionRuntime = async ({
  authorizeProjections,
  config,
  data,
  executeCells,
  invoke,
  queryWriter,
  signal,
}: WasmProjectionStartup): Promise<void> => {
  const bootstrapCell = data.executionCells.find((cell) => cell.id === data.bootstrapCellId);
  if (bootstrapCell === undefined) {
    throw new Error("The WebAssembly projection bootstrap cell is unavailable.");
  }
  throwIfWasmAborted(signal);
  await waitForWasmCaller(executeCells([bootstrapCell]), signal);
  throwIfWasmAborted(signal);
  await waitForWasmProjectionBridge(
    (requestSignal) => requestProjectionBridge(invoke, requestSignal),
    signal,
  );
  throwIfWasmAborted(signal);
  await queryWriter.write(invoke, publicNotebookQuery(globalThis.location.search));
  throwIfWasmAborted(signal);
  await authorizeProjections(invoke, config, signal);
  throwIfWasmAborted(signal);
};
