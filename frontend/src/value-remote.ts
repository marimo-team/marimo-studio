import { getRuntimeConfig, type JsonValue } from "./runtime-config.ts";
import type { ValueReadError } from "./value-state.ts";

export interface ValueReadResponse {
  values: Record<string, JsonValue>;
  errors: Record<string, ValueReadError>;
}

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

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
};

export const readValues = async (
  sessionId: string,
  selectors: string[],
  signal?: AbortSignal,
): Promise<ValueReadResponse> => {
  const config = getRuntimeConfig();
  const response = await fetch(`${config.supportUrl}/values`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Marimo-Server-Token": config.serverToken,
      "Marimo-Session-Id": sessionId,
    },
    body: JSON.stringify({ selectors }),
    signal,
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => undefined);
    const message = isRecord(payload) && typeof payload.message === "string"
      ? payload.message
      : `Value request failed with ${response.status}`;
    const code = isRecord(payload) && typeof payload.error === "string"
      ? payload.error
      : "value-request-failed";
    const transient =
      isRecord(payload) && typeof payload.transient === "boolean"
        ? payload.transient
        : false;
    throw new ValueRequestError(message, code, transient);
  }
  const payload: unknown = await response.json();
  if (
    !isRecord(payload) ||
    !isRecord(payload.values) ||
    !isRecord(payload.errors) ||
    !Object.values(payload.errors).every((error) =>
      isRecord(error) &&
      typeof error.code === "string" &&
      typeof error.message === "string"
    )
  ) {
    throw new Error("Value response has an invalid shape");
  }
  return payload as unknown as ValueReadResponse;
};

const retryDelays = [250, 500, 1_000, 2_000];

const waitForRetry = (delay: number, signal?: AbortSignal): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The request was aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timeout);
      reject(new DOMException("The request was aborted", "AbortError"));
    };
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, delay);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
};

export const readValuesWithRetry = async (
  sessionId: string,
  selectors: string[],
  signal?: AbortSignal,
): Promise<ValueReadResponse> => {
  for (let attempt = 0;; attempt += 1) {
    try {
      return await readValues(sessionId, selectors, signal);
    } catch (error) {
      if (
        !(error instanceof ValueRequestError) ||
        !error.transient ||
        attempt >= retryDelays.length
      ) {
        throw error;
      }
      await waitForRetry(retryDelays[attempt], signal);
    }
  }
};
