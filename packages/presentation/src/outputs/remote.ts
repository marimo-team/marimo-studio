import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import {
  parseOutputReadResponse,
  type OutputReadRequest,
  type OutputReadResponse,
} from "@marimo-studio/protocol/output-read";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { OutputReader } from "./reader";

import { retry } from "../retry.ts";
import { getRuntimeConfig } from "../runtime-config/index.ts";
import { reconcileOutputReadResponse } from "./reconcile";

export class OutputRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
  ) {
    super(message);
    this.name = "OutputRequestError";
  }
}

interface ServerOutputTarget {
  serverToken: string;
  url: string;
}

const serverOutputTarget = (): ServerOutputTarget => {
  const config = getRuntimeConfig();
  if (config.runtime.id !== "server") {
    throw new OutputRequestError("The server output reader is inactive.", "wrong-runtime", false);
  }
  const serverToken = config.runtime.data.serverToken;
  if (typeof serverToken !== "string") {
    throw new OutputRequestError("The server token is unavailable.", "invalid-runtime", false);
  }
  return {
    serverToken,
    url: appendUrlPath(config.supportUrl, "outputs", globalThis.location.href),
  };
};

const readServerOutputsAtTarget = async (
  target: ServerOutputTarget,
  sessionId: string,
  request: OutputReadRequest,
  signal?: AbortSignal,
): Promise<OutputReadResponse> => {
  const response = await fetch(target.url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Marimo-Server-Token": target.serverToken,
      "Marimo-Session-Id": sessionId,
    },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => undefined);
    const detail = parseErrorResponse(payload);
    throw new OutputRequestError(
      detail.message ?? `Output request failed with ${response.status}`,
      detail.error ?? "output-request-failed",
      detail.transient ?? false,
    );
  }
  return parseOutputReadResponse(await response.json());
};

const RETRY_DELAYS = [250, 500, 1_000, 2_000] as const;

const readServerOutputsAtTargetWithRetry = (
  target: ServerOutputTarget,
  sessionId: string,
  request: OutputReadRequest,
  signal?: AbortSignal,
): Promise<OutputReadResponse> =>
  retry({
    operation: () => readServerOutputsAtTarget(target, sessionId, request, signal),
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof OutputRequestError && error.transient,
    signal,
  });

const callerAbortError = (): DOMException =>
  new DOMException("The output request was cancelled.", "AbortError");

const waitForCaller = <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return operation;
  }
  if (signal.aborted) {
    return Promise.reject(callerAbortError());
  }
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(callerAbortError());
    signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
};

export const createServerOutputReader = (sessionId: string): OutputReader => {
  let queue: Promise<void> = Promise.resolve();
  return (request, signal) => {
    let target: ServerOutputTarget;
    try {
      target = serverOutputTarget();
    } catch (error) {
      return waitForCaller(Promise.reject(error), signal);
    }
    const operation = queue
      .then(() => readServerOutputsAtTargetWithRetry(target, sessionId, request))
      .then(reconcileOutputReadResponse);
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForCaller(operation, signal);
  };
};
