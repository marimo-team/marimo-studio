import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import type { EditorQuerySyncResult } from "./query-remote.ts";

import { applyFrameQuery } from "./frame-bridge.ts";
import { nextQueryWriteGeneration } from "./query-write-generation.ts";
import { RetrySchedule } from "./retry-schedule.ts";

interface PendingQuery {
  query: string;
  operationId: string;
  writeGeneration: number;
  commitOnAccept?: boolean;
  navigationIntent?: number;
  mayHaveMutated?: boolean;
  complete?: (accepted: boolean) => void;
  completionTimer?: ReturnType<typeof setTimeout>;
}

interface AbandonedNavigation {
  navigationIntent: number;
}

export interface QuerySyncStatus {
  phase: "ready" | "synchronizing" | "degraded";
  error?: Error;
}

const MAX_EXPECTED_OPERATIONS = 100;
const NAVIGATION_COMPLETION_TIMEOUT_MS = 5_000;
let operationSequence = 0;

const nextOperationId = (): string =>
  `query_${Date.now().toString(36)}_${(++operationSequence).toString(36)}`;

const pendingQuery = (
  query: string,
  options: Omit<PendingQuery, "operationId" | "query" | "writeGeneration"> = {},
): PendingQuery => ({
  query,
  operationId: nextOperationId(),
  writeGeneration: nextQueryWriteGeneration(),
  ...options,
});

export class PreviewQueryController {
  private query: string;
  private request: AbortController | undefined;
  private pending: PendingQuery | undefined;
  private active: PendingQuery | undefined;
  private readonly navigationOperations = new Map<string, PendingQuery>();
  private readonly abandonedNavigations = new Map<string, AbandonedNavigation>();
  private readonly expectedOperations = new Set<string>();
  private readonly expectedQueries = new Map<string, string>();
  private writing = false;
  private generation = 0;
  private navigationIntent = 0;
  private repairIntent: number | undefined;
  private awaitingCommitIntent: number | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RetrySchedule();
  private committedEditorQuery: string;
  private editorError: Error | undefined;
  private previewError: Error | undefined;
  private previewHash = "";
  private previewGeneration = 0;
  private previewWriting = false;
  private previewRetryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly previewRetrySchedule = new RetrySchedule();
  private lastStatus: QuerySyncStatus["phase"] = "ready";
  private lastStatusError: Error | undefined;

  constructor(
    private readonly runtime: string,
    private readonly preview: HTMLIFrameElement,
    private readonly syncQuery: (query: string) => void,
    private readonly syncEditorQuery: (
      query: string,
      operationId: string,
      writeGeneration: number,
      signal: AbortSignal,
    ) => Promise<EditorQuerySyncResult>,
    private readonly changed: () => void,
    initialQuery = globalThis.location.search,
    private readonly statusChanged: (status: QuerySyncStatus) => void = () => undefined,
  ) {
    this.query = publicNotebookQuery(initialQuery);
    this.committedEditorQuery = this.query;
  }

  get currentQuery(): string {
    return this.query;
  }

  editorChanged(query: string, viewReady: boolean, operationId?: string, completed = false): void {
    if (operationId !== undefined) {
      if (!this.expectedOperations.has(operationId)) {
        return;
      }
      if (completed) {
        this.expectedOperations.delete(operationId);
        const expectedQuery = this.expectedQueries.get(operationId);
        this.expectedQueries.delete(operationId);
        if (expectedQuery !== undefined) {
          this.committedEditorQuery = expectedQuery;
          this.editorError = undefined;
        }
        const navigation = this.navigationOperations.get(operationId);
        if (navigation !== undefined) {
          this.navigationOperations.delete(operationId);
          this.awaitingCommitIntent = navigation.navigationIntent;
          this.settle(navigation, true);
        }
        const abandoned = this.abandonedNavigations.get(operationId);
        if (abandoned !== undefined) {
          this.abandonedNavigations.delete(operationId);
          this.requestAbandonedNavigationRepair(abandoned);
        }
        this.repairCommittedQueryWhenStable();
        this.emitStatus();
      }
      return;
    }
    this.committedEditorQuery = publicNotebookQuery(query);
    this.editorError = undefined;
    if (!this.update(query)) {
      this.emitStatus();
      return;
    }
    this.supersedeNavigationTransaction();
    if (
      this.runtime !== DEFAULT_RUNTIME_ID &&
      (this.writing || this.pending !== undefined || this.retryTimer !== undefined)
    ) {
      this.setPending(pendingQuery(this.query));
      this.clearRetry();
      void this.flush();
    }
    this.repairCommittedQueryWhenStable();
    void this.applyToPreview(viewReady);
  }

  previewChanged(query: string): void {
    if (this.runtime === DEFAULT_RUNTIME_ID) {
      this.committedEditorQuery = publicNotebookQuery(query);
      this.editorError = undefined;
    }
    if (!this.update(query)) {
      return;
    }
    if (
      this.runtime === DEFAULT_RUNTIME_ID &&
      this.active?.commitOnAccept &&
      this.active.query === this.query
    ) {
      return;
    }
    this.supersedeNavigationTransaction();
    if (this.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    this.setPending(pendingQuery(this.query));
    this.clearRetry();
    void this.flush();
    this.repairCommittedQueryWhenStable();
  }

  commitNavigation(query: string): void {
    const next = publicNotebookQuery(query);
    if (next === this.query) {
      this.awaitingCommitIntent = undefined;
      this.repairCommittedQueryWhenStable();
      return;
    }
    const committedRequest =
      this.awaitingCommitIntent === this.navigationIntent &&
      this.active?.commitOnAccept === true &&
      this.active.query === next;
    this.supersedeNavigationTransaction();
    this.generation += 1;
    this.settle(this.active, false);
    this.settle(this.pending, false);
    this.navigationOperations.forEach((pending) => this.settle(pending, false));
    this.navigationOperations.clear();
    if (!committedRequest) {
      this.request?.abort();
    }
    this.request = undefined;
    this.pending = undefined;
    this.active = undefined;
    this.clearRetry();
    this.query = next;
    this.awaitingCommitIntent = undefined;
    this.repairCommittedQueryWhenStable();
    this.changed();
  }

  synchronizeNavigation(query: string): Promise<boolean> {
    return this.writeNavigation(query, false);
  }

  rollbackNavigation(query = this.query): Promise<boolean> {
    return this.writeNavigation(query, true);
  }

  private writeNavigation(query: string, force: boolean): Promise<boolean> {
    const target = publicNotebookQuery(query);
    this.supersedeNavigationTransaction();
    if (
      !force &&
      target === this.query &&
      target === this.committedEditorQuery &&
      !this.hasUnresolvedEditorWrite()
    ) {
      this.repairCommittedQueryWhenStable();
      return Promise.resolve(true);
    }
    return new Promise((resolve) => {
      this.setPending(
        pendingQuery(target, {
          commitOnAccept: true,
          navigationIntent: this.navigationIntent,
          complete: resolve,
        }),
      );
      this.clearRetry();
      void this.flush();
      this.repairCommittedQueryWhenStable();
    });
  }

  async applyToPreview(viewReady: boolean, hash?: string): Promise<void> {
    if (hash !== undefined) {
      this.previewHash = hash;
    }
    if (!viewReady) {
      return;
    }
    const generation = ++this.previewGeneration;
    const query = this.query;
    this.clearPreviewRetry();
    this.previewWriting = true;
    this.emitStatus();
    try {
      await applyFrameQuery(this.preview, query, this.previewHash);
      if (generation !== this.previewGeneration) {
        return;
      }
      this.previewError = undefined;
      this.previewRetrySchedule.reset();
    } catch (error) {
      if (generation !== this.previewGeneration) {
        return;
      }
      this.previewError = error instanceof Error ? error : new Error(String(error));
      this.schedulePreviewRetry(viewReady);
      console.warn("Marimo preview query state could not be synchronized", error);
    } finally {
      if (generation === this.previewGeneration) {
        this.previewWriting = false;
        this.emitStatus();
      }
    }
  }

  cancel(): void {
    const abandoned = this.beginCancellation();
    this.cancelNavigationTransaction(abandoned);
    this.awaitingCommitIntent = undefined;
    this.generation += 1;
    this.settle(this.active, false);
    this.settle(this.pending, false);
    this.request?.abort();
    this.request = undefined;
    this.pending = undefined;
    this.active = undefined;
    this.clearRetry();
    this.previewGeneration += 1;
    this.clearPreviewRetry();
    this.previewRetrySchedule.reset();
    this.editorError = undefined;
    this.previewError = undefined;
    this.repairCommittedQueryWhenStable();
    this.emitStatus();
  }

  cancelNavigation(): void {
    const abandoned = this.beginCancellation();
    this.cancelNavigationTransaction(abandoned);
    this.awaitingCommitIntent = undefined;
    if (this.committedEditorQuery !== this.query) {
      this.requestAbandonedNavigationRepair(abandoned);
    }
    this.repairCommittedQueryWhenStable();
  }

  private async flush(): Promise<void> {
    const pending = this.pending;
    if (this.writing || pending === undefined || this.retryTimer !== undefined) {
      return;
    }
    this.pending = undefined;
    this.writing = true;
    this.active = pending;
    const { operationId, query, writeGeneration } = pending;
    this.expectOperation(pending);
    if (pending.commitOnAccept) {
      pending.mayHaveMutated = true;
      this.navigationOperations.set(operationId, pending);
    }
    const generation = this.generation;
    const controller = new AbortController();
    this.request = controller;
    this.emitStatus();
    try {
      const result = await this.syncEditorQuery(
        query,
        operationId,
        writeGeneration,
        controller.signal,
      );
      if (result === "retry") {
        pending.mayHaveMutated = false;
        this.abandonedNavigations.delete(operationId);
      }
      if (controller.signal.aborted || generation !== this.generation) {
        return;
      }
      if (result === "retry") {
        if (pending.commitOnAccept && pending.complete === undefined) {
          this.retrySchedule.reset();
        } else if (this.pending === undefined) {
          this.pending = pending;
          this.scheduleRetry();
        } else {
          this.settle(pending, false);
        }
      } else {
        this.committedEditorQuery = query;
        this.editorError = undefined;
        if (pending.commitOnAccept) {
          this.waitForNavigationCompletion(pending);
        } else {
          this.settle(pending, true);
        }
        this.retrySchedule.reset();
      }
    } catch (error) {
      if (!pending.commitOnAccept || !controller.signal.aborted) {
        this.expectedOperations.delete(operationId);
        this.expectedQueries.delete(operationId);
      }
      if (!controller.signal.aborted) {
        pending.mayHaveMutated = false;
        this.abandonedNavigations.delete(operationId);
        this.editorError = error instanceof Error ? error : new Error(String(error));
      }
      this.navigationOperations.delete(operationId);
      this.settle(pending, false);
      if (!controller.signal.aborted) {
        if (pending.commitOnAccept) {
          this.requestAbandonedNavigationRepair({
            navigationIntent: pending.navigationIntent ?? this.navigationIntent,
          });
        } else if (this.pending === undefined) {
          this.setPending(pendingQuery(this.query));
          this.scheduleRetry();
        }
        console.warn("Marimo editor query state could not be synchronized", error);
      }
    } finally {
      if (this.active === pending) {
        this.active = undefined;
      }
      this.writing = false;
      if (this.request === controller) {
        this.request = undefined;
      }
      this.repairCommittedQueryWhenStable();
      if (this.retryTimer === undefined) {
        void this.flush();
      }
      this.emitStatus();
    }
  }

  private setPending(pending: PendingQuery): void {
    if (this.pending !== pending) {
      this.settle(this.pending, false);
    }
    this.pending = pending;
  }

  private settle(pending: PendingQuery | undefined, accepted: boolean): void {
    const complete = pending?.complete;
    if (pending !== undefined) {
      if (pending.completionTimer !== undefined) {
        clearTimeout(pending.completionTimer);
        delete pending.completionTimer;
      }
      delete pending.complete;
    }
    complete?.(accepted);
  }

  private waitForNavigationCompletion(pending: PendingQuery): void {
    if (
      pending.complete === undefined ||
      pending.completionTimer !== undefined ||
      this.navigationOperations.get(pending.operationId) !== pending
    ) {
      return;
    }
    pending.completionTimer = setTimeout(() => {
      if (this.navigationOperations.get(pending.operationId) === pending) {
        this.navigationOperations.delete(pending.operationId);
        if (pending.mayHaveMutated && pending.navigationIntent === this.navigationIntent) {
          const abandoned = {
            navigationIntent: this.navigationIntent,
          };
          this.abandonedNavigations.set(pending.operationId, abandoned);
          this.requestAbandonedNavigationRepair(abandoned);
        }
        this.settle(pending, false);
        this.repairCommittedQueryWhenStable();
      }
    }, NAVIGATION_COMPLETION_TIMEOUT_MS);
  }

  private cancelNavigationTransaction(abandoned?: AbandonedNavigation): void {
    if (this.pending?.commitOnAccept) {
      this.settle(this.pending, false);
      this.pending = undefined;
      this.clearRetry();
    }
    if (this.active?.commitOnAccept && this.active.complete !== undefined) {
      this.settle(this.active, false);
      this.request?.abort();
    }
    this.navigationOperations.forEach((pending) => {
      if (abandoned !== undefined && pending.mayHaveMutated) {
        this.abandonedNavigations.set(pending.operationId, abandoned);
      }
      this.settle(pending, false);
    });
    this.navigationOperations.clear();
  }

  private beginCancellation(): AbandonedNavigation {
    return this.retargetDispatchedNavigations();
  }

  private retargetDispatchedNavigations(): AbandonedNavigation {
    this.navigationIntent += 1;
    const abandoned = {
      navigationIntent: this.navigationIntent,
    };
    if (this.repairIntent !== undefined) {
      this.repairIntent = abandoned.navigationIntent;
    }
    for (const operationId of this.abandonedNavigations.keys()) {
      this.abandonedNavigations.set(operationId, abandoned);
    }
    return abandoned;
  }

  private supersedeNavigationTransaction(): void {
    const abandoned = this.retargetDispatchedNavigations();
    this.awaitingCommitIntent = undefined;
    this.cancelNavigationTransaction(abandoned);
  }

  private requestAbandonedNavigationRepair(abandoned: AbandonedNavigation): void {
    if (abandoned.navigationIntent !== this.navigationIntent) {
      return;
    }
    this.repairIntent = abandoned.navigationIntent;
  }

  private repairCommittedQueryWhenStable(): void {
    const repairIntent = this.repairIntent;
    if (repairIntent === undefined || repairIntent !== this.navigationIntent) {
      return;
    }
    const unresolved = (pending: PendingQuery | undefined) =>
      pending?.commitOnAccept === true &&
      pending.navigationIntent === repairIntent &&
      pending.complete !== undefined;
    if (
      this.awaitingCommitIntent === repairIntent ||
      unresolved(this.pending) ||
      unresolved(this.active) ||
      Array.from(this.navigationOperations.values()).some(unresolved)
    ) {
      return;
    }
    this.repairIntent = undefined;
    this.setPending(pendingQuery(this.query));
    this.clearRetry();
    void this.flush();
  }

  private hasUnresolvedEditorWrite(): boolean {
    return (
      this.writing ||
      this.pending !== undefined ||
      this.retryTimer !== undefined ||
      this.navigationOperations.size > 0
    );
  }

  private schedulePreviewRetry(viewReady: boolean): void {
    if (!viewReady || this.previewRetryTimer !== undefined) {
      return;
    }
    this.previewRetryTimer = setTimeout(() => {
      this.previewRetryTimer = undefined;
      void this.applyToPreview(true);
    }, this.previewRetrySchedule.next());
  }

  private clearPreviewRetry(): void {
    if (this.previewRetryTimer !== undefined) {
      clearTimeout(this.previewRetryTimer);
      this.previewRetryTimer = undefined;
    }
  }

  private emitStatus(): void {
    const error = this.editorError ?? this.previewError;
    let phase: QuerySyncStatus["phase"] = "ready";
    if (error) {
      phase = "degraded";
    } else if (
      this.hasUnresolvedEditorWrite() ||
      this.previewWriting ||
      this.previewRetryTimer !== undefined
    ) {
      phase = "synchronizing";
    }
    if (phase === this.lastStatus && error === this.lastStatusError) {
      return;
    }
    this.lastStatus = phase;
    this.lastStatusError = error;
    const status: QuerySyncStatus = { phase };
    if (error) {
      status.error = error;
    }
    this.statusChanged(status);
  }

  private scheduleRetry(): void {
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.flush();
    }, this.retrySchedule.next());
    this.emitStatus();
  }

  private clearRetry(): void {
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.retrySchedule.reset();
  }

  private update(query: string): boolean {
    const next = publicNotebookQuery(query);
    if (next === this.query) {
      return false;
    }
    this.query = next;
    this.syncQuery(query);
    this.changed();
    return true;
  }

  private expectOperation(pending: PendingQuery): void {
    const { operationId } = pending;
    if (
      !this.expectedOperations.has(operationId) &&
      this.expectedOperations.size === MAX_EXPECTED_OPERATIONS
    ) {
      const oldest = this.expectedOperations.keys().next().value;
      if (oldest !== undefined) {
        this.expectedOperations.delete(oldest);
        this.expectedQueries.delete(oldest);
        this.abandonedNavigations.delete(oldest);
      }
    }
    this.expectedOperations.add(operationId);
    this.expectedQueries.set(operationId, pending.query);
  }
}
