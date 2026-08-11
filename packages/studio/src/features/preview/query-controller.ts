import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import type { EditorQuerySyncResult } from "./query-remote.ts";

import { RetrySchedule } from "./state.ts";

interface PreviewQueryApi {
  updateQuery(query: string): Promise<void>;
}

interface PendingQuery {
  query: string;
  operationId: string;
}

const MAX_EXPECTED_OPERATIONS = 100;
let operationSequence = 0;

const nextOperationId = (): string =>
  `query_${Date.now().toString(36)}_${(++operationSequence).toString(36)}`;

export class PreviewQueryController {
  private query = publicNotebookQuery(globalThis.location.search);
  private request: AbortController | undefined;
  private pending: PendingQuery | undefined;
  private readonly expectedOperations = new Set<string>();
  private writing = false;
  private generation = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RetrySchedule();

  constructor(
    private readonly runtime: string,
    private readonly preview: HTMLIFrameElement,
    private readonly syncQuery: (query: string) => void,
    private readonly syncEditorQuery: (
      query: string,
      operationId: string,
      signal: AbortSignal,
    ) => Promise<EditorQuerySyncResult>,
    private readonly changed: () => void,
  ) {}

  editorChanged(query: string, viewReady: boolean, operationId?: string, completed = false): void {
    if (operationId && this.expectedOperations.has(operationId)) {
      if (completed) {
        this.expectedOperations.delete(operationId);
      }
      return;
    }
    if (!this.update(query)) {
      return;
    }
    if (
      this.runtime !== DEFAULT_RUNTIME_ID &&
      (this.writing || this.pending !== undefined || this.retryTimer !== undefined)
    ) {
      this.pending = {
        query: this.query,
        operationId: nextOperationId(),
      };
      this.clearRetry();
      void this.flush();
    }
    void this.applyToPreview(viewReady);
  }

  previewChanged(query: string): void {
    if (!this.update(query) || this.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    this.pending = {
      query: this.query,
      operationId: nextOperationId(),
    };
    this.clearRetry();
    void this.flush();
  }

  async applyToPreview(viewReady: boolean): Promise<void> {
    if (this.runtime === DEFAULT_RUNTIME_ID || !viewReady) {
      return;
    }
    const studio = (
      this.preview.contentWindow as
        | (Window & {
            marimoStudio?: PreviewQueryApi;
          })
        | null
    )?.marimoStudio;
    if (!studio) {
      return;
    }
    try {
      await studio.updateQuery(this.query);
    } catch (error) {
      console.warn("Marimo preview query state could not be synchronized", error);
    }
  }

  cancel(): void {
    this.generation += 1;
    this.request?.abort();
    this.request = undefined;
    this.pending = undefined;
    this.expectedOperations.clear();
    this.clearRetry();
  }

  private async flush(): Promise<void> {
    const pending = this.pending;
    if (this.writing || pending === undefined || this.retryTimer !== undefined) {
      return;
    }
    this.pending = undefined;
    this.writing = true;
    const { operationId, query } = pending;
    this.expectOperation(operationId);
    const generation = this.generation;
    const controller = new AbortController();
    this.request = controller;
    try {
      const result = await this.syncEditorQuery(query, operationId, controller.signal);
      if (controller.signal.aborted || generation !== this.generation) {
        return;
      }
      if (result === "retry") {
        this.pending ??= pending;
        this.scheduleRetry();
      } else {
        this.retrySchedule.reset();
      }
    } catch (error) {
      this.expectedOperations.delete(operationId);
      if (!controller.signal.aborted) {
        console.warn("Marimo editor query state could not be synchronized", error);
      }
    } finally {
      this.writing = false;
      if (this.request === controller) {
        this.request = undefined;
      }
      if (this.retryTimer === undefined) {
        void this.flush();
      }
    }
  }

  private scheduleRetry(): void {
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.flush();
    }, this.retrySchedule.next());
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

  private expectOperation(operationId: string): void {
    if (
      !this.expectedOperations.has(operationId) &&
      this.expectedOperations.size === MAX_EXPECTED_OPERATIONS
    ) {
      const oldest = this.expectedOperations.keys().next().value;
      if (oldest !== undefined) {
        this.expectedOperations.delete(oldest);
      }
    }
    this.expectedOperations.add(operationId);
  }
}
