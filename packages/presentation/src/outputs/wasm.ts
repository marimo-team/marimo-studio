import {
  parseOutputReadResponse,
  type OutputReadRequest,
  type OutputReadResponse,
} from "@marimo-studio/protocol/output-read";

import type { OutputReader } from "./reader";

import { functionResultSchema, throwIfWasmAborted, waitForWasmCaller } from "../values/wasm";
import { reconcileOutputReadResponse } from "./reconcile";
import { OutputRequestError } from "./remote";

export type OutputFunctionRequest = (
  request: OutputReadRequest,
  signal?: AbortSignal,
) => Promise<unknown>;

interface OutputFunctionInvocation {
  namespace: "_marimo_studio";
  functionName: "render_values";
  args: {
    selectors: string[];
    active_selectors: string[];
    consumer_id: string;
    max_output_bytes: number;
  };
}

export const createWasmOutputRequest =
  (
    consumerId: string,
    invoke: (request: OutputFunctionInvocation) => Promise<unknown>,
  ): OutputFunctionRequest =>
  (request) =>
    invoke({
      namespace: "_marimo_studio",
      functionName: "render_values",
      args: {
        selectors: request.selectors,
        active_selectors: request.activeSelectors,
        consumer_id: consumerId,
        max_output_bytes: 1_000_000,
      },
    });

const readWasmOutputs = async (
  request: OutputReadRequest,
  invoke: OutputFunctionRequest,
): Promise<OutputReadResponse> => {
  const result = functionResultSchema.parse(await invoke(request));
  if (!result.found) {
    throw new OutputRequestError(
      "The notebook output bridge is unavailable.",
      "output-bridge-unavailable",
      false,
    );
  }
  if (result.status.code !== "ok") {
    throw new OutputRequestError(
      result.status.message ?? "The notebook output bridge failed.",
      "output-bridge-failed",
      false,
    );
  }
  return parseOutputReadResponse(result.return_value);
};

export const createWasmOutputReader = (
  ready: Promise<void> | (() => Promise<void>),
  request: OutputFunctionRequest,
): OutputReader => {
  let queue: Promise<void> = Promise.resolve();
  return (projection, signal) => {
    const operation = queue.then(async () => {
      throwIfWasmAborted(signal);
      await (typeof ready === "function" ? ready() : ready);
      throwIfWasmAborted(signal);
      return readWasmOutputs(projection, request).then(reconcileOutputReadResponse);
    });
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForWasmCaller(operation, signal);
  };
};
