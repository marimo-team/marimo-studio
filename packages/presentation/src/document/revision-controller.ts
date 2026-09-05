import {
  beginProjectedOutputFunctionTransition,
  cancelProjectedOutputFunctionTransitionDrain,
  cancelProjectedOutputFunctionTransition,
  completeProjectedOutputFunctionTransition,
  type ProjectedOutputFunctionTransition,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";

import type { PresentationDiagnostic } from "../diagnostics.ts";
import type { PresentationTarget } from "./presentation-refresh.ts";
import type { DocumentRevisionCommit } from "./revision-document.ts";

import { projectionReadGate } from "../projections/read-gate.ts";
import { beginPresentationRefresh, setPresentationRefreshState } from "../readiness.ts";
import { isAbortError } from "./styles.ts";

export type RevisionOperationKind = "presentation" | "view";
export type RevisionHistoryMode = "push" | "replace";

export interface RevisionOperation {
  readonly kind: RevisionOperationKind;
  readonly target: PresentationTarget;
}

export interface RevisionFailure {
  readonly state: "loading" | "error";
  readonly diagnostic: PresentationDiagnostic;
}

export interface PresentationRevisionPolicy {
  classifyFailure(cause: unknown, operation: RevisionOperation): RevisionFailure;
  onFailure?(cause: unknown, operation: RevisionOperation, failure: RevisionFailure): void;
  onReady?(operation: RevisionOperation): void;
  onSupportChanged?(): void;
}

export interface PresentationRevisionOptions extends PresentationRevisionPolicy {
  applyRuntime(): "applied" | "pending" | "reload";
  reloadDocument(url: string): void;
  reloadRuntime(): void;
}

export interface SessionReplayPort {
  preservedUrl(target: string): string;
  remember(sessionId: string): void;
}

export interface RevisionDocumentPort {
  readonly url: string;
  abort(): void;
  replace(
    documentUrl: string,
    supportUrl: string,
    signal: AbortSignal,
    onTarget: (target: PresentationTarget) => void,
    historyMode: RevisionHistoryMode,
    historyUrl: string,
  ): Promise<DocumentRevisionCommit>;
}

export class PresentationRevisionController {
  private active: AbortController | undefined;
  private latestTransition: Promise<DocumentRevisionCommit | undefined> | undefined;
  private operationGeneration = 0;
  private disposed = false;
  private activeFunctionTransition: ProjectedOutputFunctionTransition | undefined;
  private heldFunctionTransition: ProjectedOutputFunctionTransition | undefined;

  constructor(
    private readonly document: RevisionDocumentPort,
    private readonly options: PresentationRevisionOptions,
    private readonly sessionReplay: SessionReplayPort,
  ) {}

  get url(): string {
    return this.document.url;
  }

  async transition(
    documentUrl: string,
    supportUrl: string,
    kind: RevisionOperationKind = "presentation",
    policy: PresentationRevisionPolicy = this.options,
  ): Promise<DocumentRevisionCommit | undefined> {
    return await this.transitionWithHistory(documentUrl, supportUrl, kind, policy, "replace");
  }

  async navigate(
    documentUrl: string,
    supportUrl: string,
    historyUrl = documentUrl,
    policy: PresentationRevisionPolicy = this.options,
  ): Promise<DocumentRevisionCommit | undefined> {
    return await this.transitionWithHistory(
      documentUrl,
      supportUrl,
      "view",
      policy,
      "push",
      historyUrl,
    );
  }

  async restore(
    documentUrl: string,
    supportUrl: string,
    historyUrl: string,
    policy: PresentationRevisionPolicy = this.options,
  ): Promise<DocumentRevisionCommit | undefined> {
    return await this.transitionWithHistory(
      documentUrl,
      supportUrl,
      "view",
      policy,
      "replace",
      historyUrl,
    );
  }

  private async transitionWithHistory(
    documentUrl: string,
    supportUrl: string,
    kind: RevisionOperationKind,
    policy: PresentationRevisionPolicy,
    historyMode: RevisionHistoryMode,
    historyUrl = documentUrl,
  ): Promise<DocumentRevisionCommit | undefined> {
    let reloadPending = false;
    const transitionPolicy: PresentationRevisionPolicy = {
      ...policy,
      onReady: (operation) => {
        if (!reloadPending) {
          policy.onReady?.(operation);
        }
      },
    };
    const transition = this.run(
      { kind, target: { documentUrl, supportUrl } },
      async (signal, updateTarget, cancelFunctionTransition) => {
        this.document.abort();
        const commit = await this.document.replace(
          documentUrl,
          supportUrl,
          signal,
          updateTarget,
          historyMode,
          historyUrl,
        );
        if (commit.reloadDocument) {
          reloadPending = true;
          this.options.reloadDocument(this.sessionReplay.preservedUrl(historyUrl));
          cancelFunctionTransition();
          return commit;
        }
        if (this.options.applyRuntime() === "reload") {
          reloadPending = true;
          this.options.reloadRuntime();
          cancelFunctionTransition();
        }
        if (commit.supportChanged && !reloadPending) {
          policy.onSupportChanged?.();
        }
        return commit;
      },
      transitionPolicy,
    );
    this.latestTransition = transition;
    return await transition;
  }

  async waitUntilIdle(): Promise<DocumentRevisionCommit | undefined> {
    while (this.latestTransition) {
      const transition = this.latestTransition;
      const result = await transition;
      if (this.latestTransition === transition) {
        return result;
      }
    }
    return undefined;
  }

  rememberSession(sessionId: string): void {
    this.sessionReplay.remember(sessionId);
  }

  cancel(): void {
    this.operationGeneration += 1;
    cancelProjectedOutputFunctionTransitionDrain(this.activeFunctionTransition);
    this.active?.abort();
    this.active = undefined;
    this.document.abort();
    completeProjectedOutputFunctionTransition(this.heldFunctionTransition);
    this.heldFunctionTransition = undefined;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    cancelProjectedOutputFunctionTransition(this.heldFunctionTransition);
    this.heldFunctionTransition = undefined;
    this.cancel();
    projectionReadGate.release();
    this.latestTransition = undefined;
  }

  private async run<T>(
    initialOperation: RevisionOperation,
    task: (
      signal: AbortSignal,
      updateTarget: (target: PresentationTarget) => void,
      cancelFunctionTransition: () => void,
    ) => Promise<T>,
    policy: PresentationRevisionPolicy,
  ): Promise<T | undefined> {
    if (this.disposed) {
      return undefined;
    }
    this.cancel();
    const controller = new AbortController();
    const operationGeneration = ++this.operationGeneration;
    const readinessClaim = beginPresentationRefresh("document");
    const projectionClaim = projectionReadGate.begin();
    const functionClaim = beginProjectedOutputFunctionTransition();
    let cancelFunctionTransition = false;
    let holdFunctionTransition = false;
    let operation = initialOperation;
    this.activeFunctionTransition = functionClaim;
    this.active = controller;
    try {
      await functionClaim?.drained;
      if (
        this.disposed ||
        controller.signal.aborted ||
        operationGeneration !== this.operationGeneration
      ) {
        cancelFunctionTransition ||= this.disposed;
        return undefined;
      }
      const result = await task(
        controller.signal,
        (target) => {
          operation = { ...operation, target };
        },
        () => {
          cancelFunctionTransition = true;
        },
      );
      if (
        this.disposed ||
        controller.signal.aborted ||
        operationGeneration !== this.operationGeneration
      ) {
        cancelFunctionTransition ||= this.disposed;
        return undefined;
      }
      setPresentationRefreshState(readinessClaim, "ready");
      projectionReadGate.complete(projectionClaim);
      policy.onReady?.(operation);
      return result;
    } catch (error) {
      cancelFunctionTransition ||= this.disposed;
      if (isAbortError(error) || operationGeneration !== this.operationGeneration) {
        return undefined;
      }
      const failure = policy.classifyFailure(error, operation);
      setPresentationRefreshState(readinessClaim, failure.state, failure.diagnostic);
      if (failure.state === "error") {
        projectionReadGate.complete(projectionClaim);
      } else if (!cancelFunctionTransition) {
        holdFunctionTransition = true;
      }
      policy.onFailure?.(error, operation, failure);
      throw error;
    } finally {
      if (cancelFunctionTransition) {
        cancelProjectedOutputFunctionTransition(functionClaim);
      } else if (holdFunctionTransition) {
        this.heldFunctionTransition = functionClaim;
      } else {
        completeProjectedOutputFunctionTransition(functionClaim);
      }
      if (this.active === controller) {
        this.active = undefined;
      }
      if (this.activeFunctionTransition === functionClaim) {
        this.activeFunctionTransition = undefined;
      }
    }
  }
}
