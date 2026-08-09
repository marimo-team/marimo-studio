import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import {
  parseValueReadResponse,
  type ValueReadRequest,
  type ValueReadResponse,
} from "@marimo-studio/protocol/value-read";

import { retry } from "../retry.ts";
import { getRuntimeConfig } from "../runtime-config/index.ts";

export type { ValueReadResponse } from "@marimo-studio/protocol/value-read";

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

export const readServerValues = async (
  sessionId: string,
  request: ValueReadRequest,
  signal?: AbortSignal,
): Promise<ValueReadResponse> => {
  const config = getRuntimeConfig();
  if (config.runtime.id !== "server") {
    throw new ValueRequestError("The server value reader is inactive.", "wrong-runtime", false);
  }
  const serverToken = config.runtime.data.serverToken;
  if (typeof serverToken !== "string") {
    throw new ValueRequestError("The server token is unavailable.", "invalid-runtime", false);
  }
  const response = await fetch(
    appendUrlPath(config.supportUrl, "values", globalThis.location.href),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
        "Marimo-Session-Id": sessionId,
      },
      body: JSON.stringify(request),
      signal,
    },
  );
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => undefined);
    const detail = parseErrorResponse(payload);
    const message = detail.message ?? `Value request failed with ${response.status}`;
    const code = detail.error ?? "value-request-failed";
    const transient = detail.transient ?? false;
    throw new ValueRequestError(message, code, transient);
  }
  return parseValueReadResponse(await response.json());
};

const RETRY_DELAYS = [250, 500, 1_000, 2_000] as const;

export const readServerValuesWithRetry = async (
  sessionId: string,
  request: ValueReadRequest,
  signal?: AbortSignal,
): Promise<ValueReadResponse> =>
  retry({
    operation: () => readServerValues(sessionId, request, signal),
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof ValueRequestError && error.transient,
    signal,
  });
