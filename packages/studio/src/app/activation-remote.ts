import { appendUrlPath } from "@marimo-studio/protocol/url";

export type AcknowledgeViewActivation = (
  generation: number,
  view: string,
  signal: AbortSignal,
) => Promise<void>;

const ATTEMPT_TIMEOUT_MS = 1_000;
const RETRY_DELAYS_MS = [100, 300] as const;

const wait = async (duration: number, signal: AbortSignal): Promise<void> => {
  signal.throwIfAborted();
  let cancel = () => {};
  try {
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(resolve, duration);
      cancel = () => {
        clearTimeout(timeout);
        reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      };
      signal.addEventListener("abort", cancel, { once: true });
    });
  } finally {
    signal.removeEventListener("abort", cancel);
  }
};

const retryableStatus = (status: number): boolean =>
  status === 408 || status === 429 || status >= 500;

const attemptSignal = (lifecycle: AbortSignal): { signal: AbortSignal; dispose(): void } => {
  const controller = new AbortController();
  const cancel = () => controller.abort(lifecycle.reason);
  if (lifecycle.aborted) {
    cancel();
  } else {
    lifecycle.addEventListener("abort", cancel, { once: true });
  }
  const timeout = setTimeout(
    () =>
      controller.abort(new DOMException("Activation acknowledgement timed out", "TimeoutError")),
    ATTEMPT_TIMEOUT_MS,
  );
  return {
    signal: controller.signal,
    dispose() {
      clearTimeout(timeout);
      lifecycle.removeEventListener("abort", cancel);
    },
  };
};

const acknowledge = async (
  url: string,
  serverToken: string,
  body: string,
  signal: AbortSignal,
): Promise<void> => {
  for (let attempt = 0; ; attempt += 1) {
    signal.throwIfAborted();
    const bounded = attemptSignal(signal);
    let response: Response | undefined;
    let failure: unknown;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Server-Token": serverToken,
        },
        body,
        signal: bounded.signal,
      });
    } catch (error) {
      failure = error;
    } finally {
      bounded.dispose();
    }
    if (response?.ok) {
      return;
    }
    const status = response?.status;
    const message =
      status === undefined
        ? "View activation acknowledgement failed."
        : `View activation could not be acknowledged (${status})`;
    if (status !== undefined && !retryableStatus(status)) {
      throw new Error(message, { cause: failure });
    }
    const retry = RETRY_DELAYS_MS[attempt];
    if (retry === undefined) {
      throw new Error(message, { cause: failure });
    }
    await wait(retry, signal);
  }
};

export const createViewActivationRemote =
  (agentUrl: string, serverToken: string, clientId: string): AcknowledgeViewActivation =>
  async (generation, view, signal) => {
    await acknowledge(
      appendUrlPath(agentUrl, `activations/${generation}/ack`, globalThis.location.href),
      serverToken,
      JSON.stringify({ schema: 1, clientId, view }),
      signal,
    );
  };
