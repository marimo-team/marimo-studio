import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { StagedPreviewView } from "../features/preview/deck.ts";
import type { StagedViewTransition } from "../features/views/transition.ts";

export interface StagedActiveViewHandoff {
  ready: Promise<boolean>;
  commit(): void;
  rollback(): Promise<void>;
}

export type StageActiveViewHandoff = (
  fromView: string,
  toView: string,
  signal?: AbortSignal,
) => StagedActiveViewHandoff;

export interface ActiveViewHandoffRemote {
  stage: StageActiveViewHandoff;
  dispose(): void;
}

export type RecoverActiveView = (view: string, signal: AbortSignal) => Promise<void>;

const RETRY_DELAYS_MS = [100, 300] as const;
const RELEASE_RETRY_DELAYS_MS = [100, 300, 1_000, 3_000, 5_000] as const;
const ATTEMPT_TIMEOUT_MS = 10_000;
const RELEASE_ATTEMPT_TIMEOUT_MS = 2_000;
let issuedHandoff = 0;

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

type HandoffAttempt =
  | { response: Response; failure?: never }
  | { response?: never; failure: Error };

const handoffRequest = async (
  url: string,
  serverToken: string,
  method: "POST" | "DELETE",
  body: string,
  signal: AbortSignal,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<HandoffAttempt> => {
  signal.throwIfAborted();
  const request = new AbortController();
  const cancel = () => request.abort(signal.reason);
  signal.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(
    () => request.abort(new DOMException(timeoutMessage, "TimeoutError")),
    timeoutMs,
  );
  try {
    return {
      response: await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          "Marimo-Server-Token": serverToken,
        },
        body,
        signal: request.signal,
      }),
    };
  } catch (error) {
    signal.throwIfAborted();
    return {
      failure:
        error instanceof Error
          ? error
          : new Error("Active view ownership request failed.", { cause: error }),
    };
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener("abort", cancel);
  }
};

const acquireHandoff = async (
  url: string,
  serverToken: string,
  body: string,
  signal: AbortSignal,
): Promise<void> => {
  let lastFailure = new Error("Active view ownership handoff failed.");
  for (let attempt = 0; ; attempt += 1) {
    const { response, failure } = await handoffRequest(
      url,
      serverToken,
      "POST",
      body,
      signal,
      ATTEMPT_TIMEOUT_MS,
      "View handoff timed out",
    );
    if (response?.ok) {
      return;
    }
    if (response && response.status < 500) {
      throw new Error(`Active view ownership could not be handed off (${response.status}).`);
    }
    if (response) {
      lastFailure = new Error(`Active view ownership handoff failed (${response.status}).`);
    } else if (failure) {
      lastFailure = failure;
    }
    const retry = RETRY_DELAYS_MS[attempt];
    if (retry === undefined) {
      throw lastFailure;
    }
    await wait(retry, signal);
  }
};

const releaseHandoff = async (
  url: string,
  serverToken: string,
  body: string,
  fromView: string,
  recoverAfterRelease: boolean,
  recover: RecoverActiveView,
  signal: AbortSignal,
): Promise<void> => {
  for (let attempt = 0; attempt <= RELEASE_RETRY_DELAYS_MS.length; attempt += 1) {
    const { response } = await handoffRequest(
      url,
      serverToken,
      "DELETE",
      body,
      signal,
      RELEASE_ATTEMPT_TIMEOUT_MS,
      "View release timed out",
    );
    if (response?.status === 204 && !recoverAfterRelease) {
      return;
    }
    if (response?.status === 204 || response?.status === 409) {
      break;
    }
    if (response && response.status < 500) {
      throw new Error(`Active view ownership could not be released (${response.status}).`);
    }
    const retry = RELEASE_RETRY_DELAYS_MS[attempt];
    if (retry === undefined) {
      break;
    }
    await wait(retry, signal);
  }
  await recover(fromView, signal);
};

export const createActiveViewHandoffRemote = (
  agentUrl: string,
  serverToken: string,
  clientId: string,
  recover: RecoverActiveView = async () => {
    throw new Error("Active view recovery is unavailable.");
  },
): ActiveViewHandoffRemote => {
  const lifecycle = new AbortController();
  return {
    stage(fromView, toView, signal) {
      lifecycle.signal.throwIfAborted();
      issuedHandoff += 1;
      const operationId = `active-view-${Date.now().toString(36)}-${issuedHandoff.toString(36)}`;
      const url = appendUrlPath(
        agentUrl,
        `active-view-handoffs/${operationId}`,
        globalThis.location.href,
      );
      const owner = new AbortController();
      const abortStage = () => owner.abort(signal?.reason);
      const abortLifecycle = () => owner.abort(lifecycle.signal.reason);
      signal?.addEventListener("abort", abortStage, { once: true });
      lifecycle.signal.addEventListener("abort", abortLifecycle, { once: true });
      let committed = false;
      let acquired = false;
      let rollback: Promise<void> | undefined;
      const ready = acquireHandoff(
        url,
        serverToken,
        JSON.stringify({ schema: 1, clientId, fromView, toView }),
        owner.signal,
      ).then(() => {
        acquired = true;
        return true;
      });
      const finish = () => {
        signal?.removeEventListener("abort", abortStage);
        lifecycle.signal.removeEventListener("abort", abortLifecycle);
      };
      return {
        ready,
        commit() {
          committed = true;
          finish();
        },
        rollback() {
          rollback ??= (async () => {
            if (committed) {
              return;
            }
            owner.abort(new DOMException("View handoff rolled back", "AbortError"));
            await ready.catch(() => false);
            try {
              await releaseHandoff(
                url,
                serverToken,
                JSON.stringify({ schema: 1, clientId }),
                fromView,
                !acquired,
                recover,
                lifecycle.signal,
              );
            } catch (error) {
              if (!lifecycle.signal.aborted) {
                throw error;
              }
            } finally {
              finish();
            }
          })();
          return rollback;
        },
      };
    },
    dispose() {
      lifecycle.abort(new DOMException("Studio services disposed", "AbortError"));
    },
  };
};

export const stageCommittedView = (
  preview: StagedPreviewView,
  handoff: (() => ReturnType<StageActiveViewHandoff>) | undefined,
): StagedViewTransition => {
  let ownership: ReturnType<StageActiveViewHandoff> | undefined;
  let rollback: Promise<void> | undefined;
  return {
    ready: (async () => {
      if (!(await preview.ready)) {
        return false;
      }
      ownership = handoff?.();
      return (await ownership?.ready) ?? true;
    })(),
    commit() {
      preview.commit?.();
      ownership?.commit();
    },
    rollback() {
      rollback ??= (async () => {
        const failures: unknown[] = [];
        const previewFailures = (async (): Promise<unknown[]> => {
          try {
            await preview.rollback();
            return [];
          } catch (error) {
            return [error];
          }
        })();
        try {
          await ownership?.rollback();
        } catch (error) {
          failures.push(error);
        }
        failures.push(...(await previewFailures));
        if (failures.length === 1) {
          throw failures[0];
        }
        if (failures.length > 1) {
          throw new AggregateError(failures, "The previous view could not be restored.");
        }
      })();
      return rollback;
    },
  };
};
