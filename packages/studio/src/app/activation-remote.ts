import {
  parseActivationAckResponse,
  type ActiveViewRequest,
  type PreviewAutomationTarget,
} from "@marimo-studio/protocol/development-events";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export type AcknowledgeViewActivation = (
  activation: ActiveViewRequest,
  preview: PreviewAutomationTarget,
  signal: AbortSignal,
) => Promise<void>;

interface ActivationAcknowledgement extends PreviewAutomationTarget {
  readonly schema: 2;
  readonly clientId: string;
  readonly view: string;
}

type ActivationAcknowledgementRequest =
  | ActivationAcknowledgement
  | (ActivationAcknowledgement & {
      readonly catalogGeneration: string;
      readonly viewGeneration: string | null;
    });

export class ViewActivationAcknowledgementError extends Error {
  constructor(
    readonly outcome: "rejected" | "uncertain",
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ViewActivationAcknowledgementError";
  }
}

const RETRY_DELAYS_MS = [100, 300] as const;
const ATTEMPT_TIMEOUT_MS = 10_000;

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

const acknowledge = async (
  url: string,
  serverToken: string,
  body: string,
  signal: AbortSignal,
): Promise<void> => {
  for (let attempt = 0; ; attempt += 1) {
    signal.throwIfAborted();
    const request = new AbortController();
    const cancel = () => request.abort(signal.reason);
    signal.addEventListener("abort", cancel, { once: true });
    const timeout = setTimeout(
      () => request.abort(new DOMException("Acknowledgement timed out", "TimeoutError")),
      ATTEMPT_TIMEOUT_MS,
    );
    let response: Response | undefined;
    let outcome: ReturnType<typeof parseActivationAckResponse>;
    let failure: unknown;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Server-Token": serverToken,
        },
        body,
        signal: request.signal,
      });
      outcome = parseActivationAckResponse(jsonValueSchema.parse(await response.json()));
    } catch (error) {
      failure = error;
      outcome = undefined;
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", cancel);
    }
    signal.throwIfAborted();
    if (response?.ok && outcome?.outcome === "applied") {
      return;
    }
    const status = response?.status;
    const message =
      status === undefined
        ? "View activation acknowledgement failed."
        : `View activation could not be acknowledged (${status})`;
    if (outcome?.outcome === "rejected") {
      throw new ViewActivationAcknowledgementError("rejected", message, {
        cause: failure,
      });
    }
    const retry = RETRY_DELAYS_MS[attempt];
    if (retry === undefined) {
      throw new ViewActivationAcknowledgementError("uncertain", message, {
        cause: failure,
      });
    }
    await wait(retry, signal);
  }
};

export const createViewActivationRemote =
  (agentUrl: string, serverToken: string, clientId: string): AcknowledgeViewActivation =>
  async (activation, preview, signal) => {
    const owner = activation.owner;
    const acknowledgement = {
      schema: 2,
      clientId,
      view: activation.view,
      ...preview,
    } as const;
    const request: ActivationAcknowledgementRequest =
      owner === undefined
        ? acknowledgement
        : {
            ...acknowledgement,
            catalogGeneration: owner.catalogGeneration,
            viewGeneration: owner.kind === "present" ? owner.viewGeneration : null,
          };
    await acknowledge(
      appendUrlPath(agentUrl, `activations/${activation.generation}/ack`, globalThis.location.href),
      serverToken,
      JSON.stringify(request),
      signal,
    );
  };
