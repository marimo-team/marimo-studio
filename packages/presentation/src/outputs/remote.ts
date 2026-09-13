import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import {
  parseOutputReadResponse,
  type OutputReadRequest,
  type OutputReadResponse,
} from "@marimo-studio/protocol/output-read";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { OutputReader, OutputResponseReconciler } from "./reader";

import { responseJson, responseJsonOrNull } from "../json.ts";
import { projectionWireRequest } from "../projections/identity.ts";
import { projectionReadGate } from "../projections/read-gate.ts";
import {
  notifyProjectionBindingStale,
  projectionBindingIsStale,
} from "../projections/staleness.ts";
import { retry } from "../retry.ts";
import { getRuntimeConfig } from "../runtime-config/index.ts";
import { serverRuntimeDataSchema } from "../runtime/server-config.ts";

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
  presentationSessionId: string;
  projectionRevision: string;
  revision: string;
  url: string;
}

const serverOutputTarget = (): ServerOutputTarget => {
  const config = getRuntimeConfig();
  if (config.runtime.id !== "server") {
    throw new OutputRequestError("The server output reader is inactive.", "wrong-runtime", false);
  }
  const serverData = serverRuntimeDataSchema.safeParse(config.runtime.data);
  if (!serverData.success || !config.presentationSessionId) {
    throw new OutputRequestError("The server token is unavailable.", "invalid-runtime", false);
  }
  return {
    presentationSessionId: config.presentationSessionId,
    projectionRevision: config.projectionRevision,
    revision: config.revision,
    url: appendUrlPath(config.supportUrl, "outputs", globalThis.location.href),
  };
};

const readServerOutputsAtTarget = async (
  target: ServerOutputTarget,
  request: OutputReadRequest,
  signal?: AbortSignal,
): Promise<OutputReadResponse> => {
  if (projectionBindingIsStale(target.projectionRevision)) {
    throw new OutputRequestError(
      "The presentation is refreshing its notebook bindings.",
      "stale-projection-binding",
      false,
    );
  }
  let response: Response;
  try {
    response = await fetch(target.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Session-Id": target.presentationSessionId,
      },
      body: JSON.stringify({
        ...request,
        projections: request.projections.map(projectionWireRequest),
        activeProjections: request.activeProjections.map(projectionWireRequest),
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new OutputRequestError(error.message, "output-network-failed", true);
    }
    throw error;
  }
  if (!response.ok) {
    const detail = parseErrorResponse(await responseJsonOrNull(response));
    const error = new OutputRequestError(
      detail.message ?? `Output request failed with ${response.status}`,
      detail.error ?? "output-request-failed",
      detail.transient ?? false,
    );
    notifyProjectionBindingStale(error, target.projectionRevision);
    throw error;
  }
  return parseOutputReadResponse(await responseJson(response));
};

const RETRY_DELAYS = [250, 500, 1_000, 2_000] as const;

const readServerOutputsAtTargetWithRetry = (
  target: ServerOutputTarget,
  request: OutputReadRequest,
  signal?: AbortSignal,
): Promise<OutputReadResponse> =>
  retry({
    operation: () => readServerOutputsAtTarget(target, request, signal),
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof OutputRequestError && error.transient,
    signal,
  });

export const outputCallerAbortError = (): DOMException =>
  new DOMException("The output request was cancelled.", "AbortError");

export const waitForOutputCaller = <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return operation;
  }
  if (signal.aborted) {
    return Promise.reject(outputCallerAbortError());
  }
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(outputCallerAbortError());
    signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
};

export const createServerOutputReader = (reconcile: OutputResponseReconciler): OutputReader => {
  let queue: Promise<void> = Promise.resolve();
  return (request, signal) => {
    const operation = queue.then(async () => {
      if (signal?.aborted) {
        throw outputCallerAbortError();
      }
      try {
        return await projectionReadGate.run(signal, (activeSignal) => {
          const target = serverOutputTarget();
          return readServerOutputsAtTargetWithRetry(
            target,
            { ...request, revision: target.revision },
            activeSignal,
          );
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError" && !signal?.aborted) {
          throw new OutputRequestError(error.message, "output-read-interrupted", true);
        }
        throw error;
      }
    });
    queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return waitForOutputCaller(operation, signal).then(reconcile);
  };
};
