import type { ShellChangeKind } from "@marimo-studio/protocol/development-events";

import type { PresentationDiagnostic } from "../diagnostics.ts";
import type { RuntimeConfig } from "../runtime-config/index.ts";
import type { ShellTarget } from "./refresh-state.ts";
import type { DocumentRevisionCommit } from "./revision-document.ts";

import { beginPresentationRefresh, setPresentationRefreshState } from "../readiness.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getRuntimeConfig,
  getSupportUrl,
} from "../runtime-config/index.ts";
import { isAbortError } from "./styles.ts";

export interface RevisionOperation {
  readonly kind: ShellChangeKind;
  readonly target: ShellTarget;
}

export interface RevisionFailure {
  readonly state: "loading" | "error";
  readonly diagnostic: PresentationDiagnostic;
}

export interface PresentationRevisionPolicy {
  classifyFailure(error: unknown, operation: RevisionOperation): RevisionFailure;
  onFailure?(error: unknown, operation: RevisionOperation, failure: RevisionFailure): void;
  onReady?(operation: RevisionOperation): void;
  onSupportChanged?(): void;
}

export interface PresentationRevisionOptions extends PresentationRevisionPolicy {
  applyRuntime(): "applied" | "pending" | "reload";
  loadRevision(
    config: RuntimeConfig,
    previewSessionId: string,
    signal: AbortSignal,
  ): Promise<RuntimeConfig>;
  reloadDocument(url: string): void;
  reloadRuntime(): void;
}

export interface SessionReplayPort {
  prepare(config: RuntimeConfig): boolean;
  preservedUrl(target: string): string;
  finish(): void;
  remember(sessionId: string): void;
}

export interface RevisionDocumentPort {
  readonly url: string;
  abort(): void;
  refreshStylesheets(): Promise<void>;
  replace(
    documentUrl: string,
    supportUrl: string,
    signal: AbortSignal,
    onTarget: (target: ShellTarget) => void,
  ): Promise<DocumentRevisionCommit>;
}

export class PresentationRevisionController {
  private active: AbortController | undefined;
  private operationGeneration = 0;
  private disposed = false;

  constructor(
    private readonly document: RevisionDocumentPort,
    private readonly previewSessionId: string,
    private readonly options: PresentationRevisionOptions,
    private readonly sessionReplay: SessionReplayPort,
  ) {}

  get url(): string {
    return this.document.url;
  }

  async transition(
    documentUrl: string,
    supportUrl: string,
    kind: ShellChangeKind = "html",
    policy: PresentationRevisionPolicy = this.options,
  ): Promise<DocumentRevisionCommit | undefined> {
    return await this.run(
      { kind, target: { documentUrl, supportUrl } },
      async (signal, updateTarget) => {
        this.document.abort();
        const commit = await this.document.replace(documentUrl, supportUrl, signal, updateTarget);
        if (commit.reloadDocument) {
          this.options.reloadDocument(this.sessionReplay.preservedUrl(commit.target.documentUrl));
          return commit;
        }
        if (this.options.applyRuntime() === "reload") {
          this.options.reloadRuntime();
        }
        if (commit.supportChanged) {
          policy.onSupportChanged?.();
        }
        return commit;
      },
      policy,
    );
  }

  async refreshStyles(policy: PresentationRevisionPolicy = this.options): Promise<void> {
    await this.run(
      {
        kind: "css",
        target: { documentUrl: this.document.url, supportUrl: getSupportUrl() },
      },
      async (signal) => {
        await this.document.refreshStylesheets();
        await this.refreshRuntimeConfig(signal);
      },
      policy,
    );
  }

  async refreshRuntime(policy: PresentationRevisionPolicy = this.options): Promise<void> {
    await this.run(
      {
        kind: "runtime",
        target: { documentUrl: this.document.url, supportUrl: getSupportUrl() },
      },
      async (signal) => {
        this.document.abort();
        await this.refreshRuntimeConfig(signal);
      },
      policy,
    );
  }

  async resume(config: RuntimeConfig): Promise<RuntimeConfig> {
    if (!this.sessionReplay.prepare(config)) {
      return config;
    }
    const resumed = await this.run(
      {
        kind: "runtime",
        target: {
          documentUrl: this.document.url,
          supportUrl: config.supportUrl,
        },
      },
      async (signal) =>
        commitRuntimeConfig(await this.options.loadRevision(config, this.previewSessionId, signal)),
      this.options,
    );
    if (resumed === undefined) {
      return config;
    }
    document.addEventListener("marimo-studio:runtime-ready", () => this.sessionReplay.finish(), {
      once: true,
    });
    return resumed;
  }

  rememberSession(sessionId: string): void {
    this.sessionReplay.remember(sessionId);
  }

  cancel(): void {
    this.operationGeneration += 1;
    this.active?.abort();
    this.active = undefined;
    this.document.abort();
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.cancel();
  }

  private async refreshRuntimeConfig(signal: AbortSignal): Promise<void> {
    commitRuntimeConfig(
      await fetchRuntimeConfig(
        getSupportUrl(),
        signal,
        getRuntimeConfig().runtime.id,
        this.previewSessionId,
      ),
    );
    if (this.options.applyRuntime() === "reload") {
      this.options.reloadRuntime();
    }
  }

  private async run<T>(
    initialOperation: RevisionOperation,
    task: (signal: AbortSignal, updateTarget: (target: ShellTarget) => void) => Promise<T>,
    policy: PresentationRevisionPolicy,
  ): Promise<T | undefined> {
    if (this.disposed) {
      return undefined;
    }
    this.cancel();
    const controller = new AbortController();
    const operationGeneration = ++this.operationGeneration;
    const readinessGeneration = beginPresentationRefresh();
    let operation = initialOperation;
    this.active = controller;
    try {
      const result = await task(controller.signal, (target) => {
        operation = { ...operation, target };
      });
      if (
        this.disposed ||
        controller.signal.aborted ||
        operationGeneration !== this.operationGeneration
      ) {
        return undefined;
      }
      setPresentationRefreshState(readinessGeneration, "ready");
      policy.onReady?.(operation);
      return result;
    } catch (error) {
      if (isAbortError(error) || operationGeneration !== this.operationGeneration) {
        return undefined;
      }
      const failure = policy.classifyFailure(error, operation);
      setPresentationRefreshState(readinessGeneration, failure.state, failure.diagnostic);
      policy.onFailure?.(error, operation, failure);
      throw error;
    } finally {
      if (this.active === controller) {
        this.active = undefined;
      }
    }
  }
}
