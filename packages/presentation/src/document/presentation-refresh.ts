import { ProjectedOutputFunctionDrainTimeoutError } from "@marimo-studio/marimo-frontend/projected-output-function-gate";

import type { PresentationDiagnostic } from "../diagnostics.ts";

import { errorMessage } from "../errors.ts";
import { RuntimeConfigRequestError } from "../runtime-config/index.ts";
import { StylesheetRefreshError } from "./styles.ts";

export interface PresentationTarget {
  documentUrl: string;
  supportUrl: string;
}

export interface VersionedPresentationTarget extends PresentationTarget {
  revision: string;
}

export const samePresentationRevision = (
  current: VersionedPresentationTarget,
  next: VersionedPresentationTarget,
): boolean => current.revision === next.revision;

export class RefreshRetrySchedule {
  #attempt = 0;

  constructor(private readonly delays: readonly number[] = [1_000, 2_000, 5_000, 10_000, 30_000]) {
    if (delays.length === 0) {
      throw new Error("Refresh retry schedule requires at least one delay");
    }
  }

  next(): number {
    const delay = this.delays[Math.min(this.#attempt, this.delays.length - 1)];
    this.#attempt += 1;
    return delay;
  }

  reset(): void {
    this.#attempt = 0;
  }
}

export class BaselineReconciler {
  #configured: boolean;
  #pending = false;

  constructor(configured: boolean) {
    this.#configured = configured;
  }

  ready(refreshRequired = false): boolean {
    if (!this.#configured) {
      this.#pending = true;
    }
    return this.#configured && refreshRequired;
  }

  configure(): boolean {
    this.#configured = true;
    if (!this.#pending) {
      return false;
    }
    this.#pending = false;
    return true;
  }
}

export class StaleBindingRefresh {
  #revision: string | undefined;

  request(revision: string): boolean {
    if (this.#revision === revision) {
      return false;
    }
    this.#revision = revision;
    return true;
  }

  needsRetry(currentRevision: string): boolean {
    if (this.#revision === undefined) {
      return false;
    }
    if (this.#revision === currentRevision) {
      return true;
    }
    this.#revision = undefined;
    return false;
  }

  clear(): void {
    this.#revision = undefined;
  }
}

export class PresentationRefreshState {
  #failedTarget: PresentationTarget | undefined;

  get failedTarget(): PresentationTarget | undefined {
    return this.#failedTarget && { ...this.#failedTarget };
  }

  rememberFailure(target: PresentationTarget): void {
    this.#failedTarget = target;
  }

  supersede(): void {
    this.#failedTarget = undefined;
  }

  complete(target: PresentationTarget): void {
    if (
      this.#failedTarget?.documentUrl === target.documentUrl &&
      this.#failedTarget.supportUrl === target.supportUrl
    ) {
      this.#failedTarget = undefined;
    }
  }
}

const refreshFailureCode = (cause: unknown): string => {
  if (cause instanceof RuntimeConfigRequestError || cause instanceof StylesheetRefreshError) {
    return cause.code;
  }
  if (cause instanceof ProjectedOutputFunctionDrainTimeoutError) {
    return "presentation-refresh-waiting-for-function";
  }
  return "presentation-refresh-failed";
};

const refreshFailureHint = (cause: unknown, transient: boolean): string => {
  if (cause instanceof RuntimeConfigRequestError && cause.hint) {
    return cause.hint;
  }
  if (cause instanceof ProjectedOutputFunctionDrainTimeoutError) {
    return "Wait for the running widget request to finish. The preview refreshes after it does.";
  }
  return transient
    ? "Wait for Marimo to accept the notebook change."
    : "Fix the view source, then save it again.";
};

/**
 * Describe a failed presentation refresh. A warning means the refresh retries
 * on its own, and an error waits for the author to change the view.
 */
export const refreshDiagnostic = (cause: unknown, view: string): PresentationDiagnostic => {
  const transient =
    (cause instanceof RuntimeConfigRequestError && cause.transient) ||
    cause instanceof ProjectedOutputFunctionDrainTimeoutError;
  return {
    scope: "presentation",
    code: refreshFailureCode(cause),
    severity: transient ? "warning" : "error",
    message: errorMessage(cause),
    hint: refreshFailureHint(cause, transient),
    view,
    details: cause instanceof RuntimeConfigRequestError ? cause.details : undefined,
  };
};
