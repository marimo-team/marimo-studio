import type { BrowserObservation } from "@marimo-studio/protocol/browser-observations";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export type RenderedBrowserObservation = Omit<
  BrowserObservation,
  "schema" | "clientId" | "sequence"
>;
export type RecordBrowserObservation = (observation: RenderedBrowserObservation) => Promise<void>;

const ATTEMPT_TIMEOUT_MS = 3_000;
const RETRY_DELAYS_MS = [100, 300] as const;

export class BrowserObservationUploadError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: string,
    readonly retryable: boolean,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "BrowserObservationUploadError";
  }
}

const delay = async (duration: number, signal: AbortSignal): Promise<boolean> => {
  if (signal.aborted) {
    return false;
  }
  return await new Promise((resolve) => {
    const timeout = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve(true);
    }, duration);
    const cancel = () => {
      clearTimeout(timeout);
      resolve(false);
    };
    signal.addEventListener("abort", cancel, { once: true });
  });
};

const responseError = async (response: Response): Promise<BrowserObservationUploadError> => {
  let code = "browser-observation-upload-failed";
  try {
    const detail = parseErrorResponse(await response.json());
    if (detail.error !== undefined) {
      code = detail.error;
    }
  } catch {
    // The status still provides a stable retry classification.
  }
  const retryable = response.status === 408 || response.status === 429 || response.status >= 500;
  return new BrowserObservationUploadError(
    `Browser observation could not be recorded (${response.status})`,
    response.status,
    code,
    retryable,
  );
};

const upload = async (
  url: string,
  serverToken: string,
  payload: BrowserObservation,
  timeoutMs: number,
  signal: AbortSignal,
) => {
  signal.throwIfAborted();
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  signal.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await responseError(response);
    }
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    if (error instanceof BrowserObservationUploadError) {
      throw error;
    }
    throw new BrowserObservationUploadError(
      controller.signal.aborted
        ? "Browser observation upload timed out."
        : "Browser observation upload failed.",
      null,
      controller.signal.aborted
        ? "browser-observation-upload-timeout"
        : "browser-observation-network-error",
      true,
      { cause: error },
    );
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", cancel);
  }
};

const uploadWithRetry = async (
  url: string,
  serverToken: string,
  payload: BrowserObservation,
  signal: AbortSignal,
): Promise<void> => {
  const retryDelays = payload.state === "loading" ? [] : RETRY_DELAYS_MS;
  const timeout = payload.state === "loading" ? 750 : ATTEMPT_TIMEOUT_MS;
  for (let attempt = 0; ; attempt += 1) {
    if (signal.aborted) {
      return;
    }
    try {
      await upload(url, serverToken, payload, timeout, signal);
      return;
    } catch (error) {
      if (signal.aborted) {
        return;
      }
      const retry = retryDelays[attempt];
      if (
        !(error instanceof BrowserObservationUploadError) ||
        !error.retryable ||
        retry === undefined
      ) {
        throw error;
      }
      if (!(await delay(retry, signal))) {
        return;
      }
    }
  }
};

export const createBrowserObservationRemote = (
  supportUrl: (view: string) => string,
  serverToken: string,
  clientId: string,
): RecordBrowserObservation => {
  let sequence = 0;
  let active:
    | {
        requestId: string;
        controller: AbortController;
        pending: Promise<void>;
      }
    | undefined;
  return async (observation) => {
    const payload: BrowserObservation = {
      ...observation,
      schema: 1,
      clientId,
      sequence: sequence++,
    };
    if (active?.requestId !== observation.requestId) {
      active?.controller.abort();
      active = {
        requestId: observation.requestId,
        controller: new AbortController(),
        pending: Promise.resolve(),
      };
    }
    const request = active;
    const send = async () =>
      await uploadWithRetry(
        appendUrlPath(supportUrl(observation.view), "observation", globalThis.location.href),
        serverToken,
        payload,
        request.controller.signal,
      );
    request.pending = request.pending.catch(() => undefined).then(send);
    await request.pending;
  };
};
