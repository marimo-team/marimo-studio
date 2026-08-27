import type { EmbeddedFunction } from "@marimo-studio/marimo-frontend/embedded-runtime";

import {
  parseOutputReadResponse,
  type OutputReadRequest,
  type OutputReadResponse,
} from "@marimo-studio/protocol/output-read";

import type { FunctionResult } from "../values/wasm";
import type { OutputReader, OutputResponseReconciler } from "./reader";

import { projectionWireRequest } from "../projections/identity";
import { functionResultSchema, throwIfWasmAborted, waitForWasmCaller } from "../values/wasm";
import { WASM_PROJECTION_NAMESPACE } from "../wasm-rpc";
import { OutputRequestError } from "./remote";

export type OutputFunctionRequest = (
  request: OutputReadRequest,
  signal?: AbortSignal,
) => Promise<FunctionResult>;

interface OutputFunctionInvocation {
  namespace: typeof WASM_PROJECTION_NAMESPACE;
  functionName: "render_values";
  args: {
    revision: string;
    projections: OutputReadRequest["projections"];
    active_projections: OutputReadRequest["activeProjections"];
    consumer_id: string;
    max_output_bytes: number;
  };
}

export const createWasmOutputRequest =
  (
    consumerId: string,
    invoke: EmbeddedFunction,
    authorize: (request: OutputReadRequest, signal?: AbortSignal) => Promise<void>,
  ): OutputFunctionRequest =>
  async (request, signal) => {
    await authorize(request, signal);
    const invocation: OutputFunctionInvocation = {
      namespace: WASM_PROJECTION_NAMESPACE,
      functionName: "render_values",
      args: {
        revision: request.revision,
        projections: request.projections.map(projectionWireRequest),
        active_projections: request.activeProjections.map(projectionWireRequest),
        consumer_id: consumerId,
        max_output_bytes: 1_000_000,
      },
    };
    return functionResultSchema.parse(await invoke(invocation));
  };

const readWasmOutputs = async (
  request: OutputReadRequest,
  invoke: OutputFunctionRequest,
  signal?: AbortSignal,
): Promise<OutputReadResponse> => {
  const result = await (signal ? invoke(request, signal) : invoke(request));
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
  ready: () => Promise<void>,
  request: OutputFunctionRequest,
  reconcile: OutputResponseReconciler,
): OutputReader => {
  let queue: Promise<void> = Promise.resolve();
  return (projection, signal) => {
    const operation = queue.then(async () => {
      throwIfWasmAborted(signal);
      await ready();
      throwIfWasmAborted(signal);
      return readWasmOutputs(projection, request, signal);
    });
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForWasmCaller(operation, signal).then(reconcile);
  };
};
