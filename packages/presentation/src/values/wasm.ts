import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { parseValueReadResponse, type ValueReadResponse } from "@marimo-studio/protocol/value-read";
import { z } from "zod";

import type { ValueReader } from "./reader";

import { ValueRequestError } from "./remote";

export const functionResultSchema = z.object({
  found: z.boolean(),
  status: z.object({ code: z.string(), message: z.string().nullish() }),
  return_value: jsonValueSchema,
});

export type FunctionResult = z.infer<typeof functionResultSchema>;

const BRIDGE_RETRY_DELAY_MS = 250;

export type FunctionRequest = (
  selectors: string[],
  signal?: AbortSignal,
) => Promise<FunctionResult>;

const abortError = (): DOMException =>
  new DOMException("The runtime request was cancelled.", "AbortError");

export const throwIfWasmAborted = (signal?: AbortSignal): void => {
  if (signal?.aborted) {
    throw abortError();
  }
};

const wait = (delay: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const abort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delay);
    signal?.addEventListener("abort", abort, { once: true });
  });

export const waitForWasmCaller = <T>(request: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return request;
  }
  if (signal.aborted) {
    return Promise.reject(abortError());
  }
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(abortError());
    signal.addEventListener("abort", abort, { once: true });
    request.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
};

const readWasmValues = async (
  selectors: string[],
  request: FunctionRequest,
): Promise<ValueReadResponse> => {
  const result = await request(selectors);
  if (!result.found) {
    throw new ValueRequestError(
      "The notebook value bridge is unavailable.",
      "value-bridge-unavailable",
      false,
    );
  }
  if (result.status.code !== "ok") {
    throw new ValueRequestError(
      result.status.message ?? "The notebook value bridge failed.",
      "value-bridge-failed",
      false,
    );
  }
  return parseValueReadResponse(result.return_value);
};

export const waitForWasmValueBridge = async (
  request: FunctionRequest,
  signal: AbortSignal,
): Promise<void> => {
  // The injected function enters the same kernel queue as notebook
  // instantiation. A successful call therefore proves that dependencies
  // loaded, the initial graph settled, and its Python controls exist.
  while (!signal.aborted) {
    const result = await waitForWasmCaller(request([], signal), signal);
    if (result.found) {
      if (result.status.code !== "ok") {
        throw new ValueRequestError(
          result.status.message ?? "The notebook value bridge failed.",
          "value-bridge-failed",
          false,
        );
      }
      return;
    }
    await wait(BRIDGE_RETRY_DELAY_MS, signal);
  }
  throw abortError();
};

/** Serialize bridge calls so cancellation never multiplies work in Pyodide. */
export const createWasmValueReader = (
  ready: () => Promise<void>,
  request: FunctionRequest,
): ValueReader => {
  let queue: Promise<void> = Promise.resolve();
  return ({ selectors }, signal) => {
    const operation = queue.then(async () => {
      throwIfWasmAborted(signal);
      await ready();
      throwIfWasmAborted(signal);
      return readWasmValues(selectors, (requested) => request(requested, signal));
    });
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForWasmCaller(operation, signal);
  };
};
