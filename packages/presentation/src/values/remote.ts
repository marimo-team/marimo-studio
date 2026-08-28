import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import { parseValueReadResponse, type ValueReadRequest } from "@marimo-studio/protocol/value-read";

import type { DecodedValueReadResponse } from "./codecs.ts";

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
import { createValueDecoder, ValueDecodeError } from "./codecs.ts";

export class ValueRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
  ) {
    super(message);
    this.name = "ValueRequestError";
  }
}

const decodeServerValues = createValueDecoder();

const valueResourceBaseUrl = (supportUrl: string): URL => {
  const url = new URL(supportUrl, globalThis.location.href);
  const marker = "/_marimo-studio/views/";
  const markerIndex = url.pathname.lastIndexOf(marker);
  if (markerIndex < 0) {
    throw new ValueRequestError(
      "The server value resource authority is unavailable.",
      "invalid-runtime",
      false,
    );
  }
  url.pathname = `${url.pathname.slice(0, markerIndex)}/`;
  url.search = "";
  url.hash = "";
  return url;
};

export const readServerValues = async (
  request: ValueReadRequest,
  signal?: AbortSignal,
): Promise<DecodedValueReadResponse> =>
  projectionReadGate.run(signal, async (activeSignal) => {
    const config = getRuntimeConfig();
    if (projectionBindingIsStale(config.projectionRevision)) {
      throw new ValueRequestError(
        "The presentation is refreshing its notebook bindings.",
        "stale-projection-binding",
        false,
      );
    }
    if (config.runtime.id !== "server") {
      throw new ValueRequestError("The server value reader is inactive.", "wrong-runtime", false);
    }
    const serverData = serverRuntimeDataSchema.safeParse(config.runtime.data);
    if (!serverData.success || !config.presentationSessionId) {
      throw new ValueRequestError("The server token is unavailable.", "invalid-runtime", false);
    }
    let response: Response;
    try {
      response = await fetch(appendUrlPath(config.supportUrl, "values", globalThis.location.href), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Session-Id": config.presentationSessionId,
        },
        body: JSON.stringify({
          ...request,
          revision: config.revision,
          projections: request.projections.map(projectionWireRequest),
          activeProjections: request.activeProjections.map(projectionWireRequest),
        }),
        signal: activeSignal,
      });
    } catch (error) {
      if (error instanceof TypeError) {
        throw new ValueRequestError(error.message, "value-network-failed", true);
      }
      throw error;
    }
    if (!response.ok) {
      const detail = parseErrorResponse(await responseJsonOrNull(response));
      const message = detail.message ?? `Value request failed with ${response.status}`;
      const code = detail.error ?? "value-request-failed";
      const transient = detail.transient ?? false;
      const error = new ValueRequestError(message, code, transient);
      notifyProjectionBindingStale(error, config.projectionRevision);
      throw error;
    }
    const encoded = parseValueReadResponse(await responseJson(response));
    try {
      return await decodeServerValues(encoded, {
        activeSelectors: request.activeProjections.map((projection) => projection.target),
        baseUrl: valueResourceBaseUrl(config.supportUrl),
        scope: config.projectionRevision,
        signal: activeSignal,
      });
    } catch (error) {
      if (error instanceof ValueDecodeError && error.transient) {
        throw new ValueRequestError(error.message, error.code, true);
      }
      throw error;
    }
  });

const RETRY_DELAYS = [250, 500, 1_000, 2_000] as const;

export const readServerValuesWithRetry = async (
  request: ValueReadRequest,
  signal?: AbortSignal,
): Promise<DecodedValueReadResponse> =>
  retry({
    operation: () => readServerValues(request, signal),
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof ValueRequestError && error.transient,
    signal,
  });
