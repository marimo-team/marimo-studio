import {
  parsePreviewMessage,
  type PresentationToStudioMessage,
  type SwitchViewMessage,
  type ViewDiagnostic,
  type ViewPreviewMessage,
} from "@marimo-studio/protocol/preview-messages";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import { assertNever } from "../../shared/assertNever.ts";
import { fetchRuntimeControls } from "./control-remote.ts";
import {
  type ControlFrameConnector,
  type ControlSync,
  synchronizeControlEndpoints,
} from "./control-sync.ts";
import { previewLoadState, RetrySchedule } from "./state.ts";
import { previewStartingMessage, type PreviewStatus } from "./status.ts";

const CONTROL_SYNC_RETRY_DELAYS = [100, 250, 500, 1_000, 2_000, 5_000] as const;

export interface PreviewFrameState {
  url: string;
  status: PreviewStatus;
}

export class PreviewController {
  private view: string;
  private state: PreviewFrameState;
  private receiverReady = false;
  private viewReady = false;
  private diagnostics: ViewDiagnostic[] = [];
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RetrySchedule();
  private controlSync: ControlSync | undefined;
  private controlSyncRevision: string | undefined;
  private controlSyncRequest: { controller: AbortController; revision: string } | undefined;
  private controlSyncRetryTimer: ReturnType<typeof setTimeout> | undefined;
  private controlSyncRetryAttempt = 0;
  private readyRevision: string | undefined;
  private notebookQuery = publicNotebookQuery(globalThis.location.search);
  private querySyncController: AbortController | undefined;

  constructor(
    initialView: string,
    private readonly runtime: string,
    private readonly editor: HTMLIFrameElement,
    private readonly preview: HTMLIFrameElement,
    private readonly viewUrl: (view: string, runtime: string) => string,
    private readonly supportUrl: (view: string) => string,
    private readonly syncQuery: (query: string) => void,
    private readonly syncEditorQuery: (query: string, signal: AbortSignal) => Promise<void>,
    private readonly navigate: (view: string) => void,
    private readonly report: (state: PreviewFrameState) => void,
    private readonly connectControlFrame?: ControlFrameConnector,
  ) {
    this.view = initialView;
    this.state = {
      url: this.viewUrl(initialView, runtime),
      status: {
        message: previewStartingMessage(runtime),
        state: "loading",
        title: "",
      },
    };
    this.bind();
  }

  switchView(view: string): void {
    this.stopControlSync();
    this.readyRevision = undefined;
    this.viewReady = false;
    this.view = view;
    const nextPreview = this.viewUrl(view, this.runtime);
    this.preview.title = `${view} custom view using ${this.runtime}`;
    this.setPopoutUrl(nextPreview);
    this.diagnostics = [];
    this.setStatus("Updating preview");
    if (this.receiverReady) {
      this.postSwitch();
    } else {
      this.retrySchedule.reset();
      this.reload();
    }
  }

  requestResize(): void {
    this.preview.contentWindow?.dispatchEvent(new Event("resize"));
  }

  editorQueryChanged(query: string): void {
    if (this.queryChanged(query)) {
      void this.updatePreviewQuery(this.notebookQuery);
    }
  }

  dispose(): void {
    this.cancelRetry();
    this.stopControlSync();
    this.querySyncController?.abort();
    this.editor.removeEventListener("load", this.editorLoaded);
    this.editor.removeEventListener("load", this.startFromEditor);
    this.preview.removeEventListener("load", this.previewLoaded);
    globalThis.removeEventListener("message", this.message);
  }

  private bind(): void {
    globalThis.addEventListener("message", this.message);
    this.preview.addEventListener("load", this.previewLoaded);
    this.editor.addEventListener("load", this.editorLoaded);
    this.editor.addEventListener("load", this.startFromEditor, { once: true });
    if (this.editor.contentDocument?.readyState === "complete") {
      this.startFromEditor();
    }
  }

  private readonly startFromEditor = (): void => {
    this.editor.removeEventListener("load", this.startFromEditor);
    if (this.preview.src === "about:blank") {
      this.reload();
    }
  };

  private readonly message = (event: MessageEvent<unknown>) => {
    if (
      event.origin !== globalThis.location.origin ||
      event.source !== this.preview.contentWindow
    ) {
      return;
    }
    const message = parsePreviewMessage(event.data);
    if (
      !message ||
      message.type === "marimo-studio:switch-view" ||
      message.runtime !== this.runtime
    ) {
      return;
    }
    this.receive(message);
  };

  private receive(message: PresentationToStudioMessage): void {
    switch (message.type) {
      case "marimo-studio:navigate-view":
        this.navigate(message.view);
        return;
      case "marimo-studio:query-change":
        this.previewQueryChanged(message.query);
        return;
      case "marimo-studio:receiver-ready":
        this.stopControlSync();
        this.readyRevision = undefined;
        this.receiverReady = true;
        this.viewReady = false;
        this.cancelRetry();
        this.retrySchedule.reset();
        if (message.view === this.view) {
          this.setStatus(previewStartingMessage(this.runtime));
        } else {
          this.postSwitch();
        }
        return;
      case "marimo-studio:view-ready":
      case "marimo-studio:view-sync-pending":
      case "marimo-studio:view-diagnostics":
      case "marimo-studio:view-error":
        if (message.view === this.view) {
          this.receiveView(message);
        }
        return;
      default:
        assertNever(message);
    }
  }

  private receiveView(message: ViewPreviewMessage): void {
    switch (message.type) {
      case "marimo-studio:view-ready":
        if (message.sessionId !== undefined) {
          this.preview.dataset.sessionId = message.sessionId;
        }
        this.readyRevision = message.revision;
        this.viewReady = true;
        this.showDiagnostics();
        this.beginControlSync(message.revision);
        void this.updatePreviewQuery(this.notebookQuery);
        return;
      case "marimo-studio:view-sync-pending":
        this.viewReady = false;
        this.setStatus("Waiting for notebook", "loading", message.hint);
        return;
      case "marimo-studio:view-diagnostics":
        this.diagnostics = message.diagnostics;
        if (this.viewReady) {
          this.showDiagnostics();
        }
        return;
      case "marimo-studio:view-error":
        this.viewReady = false;
        this.setStatus("Needs repair", "error", message.hint);
        return;
      default:
        assertNever(message);
    }
  }

  private queryChanged(query: string): boolean {
    const next = publicNotebookQuery(query);
    if (next === this.notebookQuery) {
      return false;
    }
    this.notebookQuery = next;
    this.syncQuery(query);
    this.setPopoutUrl(this.viewUrl(this.view, this.runtime));
    return true;
  }

  private previewQueryChanged(query: string): void {
    if (!this.queryChanged(query) || this.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    this.querySyncController?.abort();
    const controller = new AbortController();
    this.querySyncController = controller;
    void this.syncEditorQuery(this.notebookQuery, controller.signal)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn("Marimo editor query state could not be synchronized", error);
        }
      })
      .finally(() => {
        if (this.querySyncController === controller) {
          this.querySyncController = undefined;
        }
      });
  }

  private async updatePreviewQuery(query: string): Promise<void> {
    if (this.runtime === DEFAULT_RUNTIME_ID || !this.viewReady) {
      return;
    }
    const studio = (
      this.preview.contentWindow as
        | (Window & { marimoStudio?: { updateQuery(query: string): Promise<void> } })
        | null
    )?.marimoStudio;
    if (!studio) {
      return;
    }
    try {
      await studio.updateQuery(query);
    } catch (error) {
      console.warn("Marimo preview query state could not be synchronized", error);
    }
  }

  private postSwitch(): void {
    const message: SwitchViewMessage = {
      type: "marimo-studio:switch-view",
      runtime: this.runtime,
      view: this.view,
      documentUrl: this.viewUrl(this.view, this.runtime),
      supportUrl: this.supportUrl(this.view),
    };
    this.preview.contentWindow?.postMessage(message, globalThis.location.origin);
  }

  private reload(): void {
    this.cancelRetry();
    this.stopControlSync();
    this.querySyncController?.abort();
    this.readyRevision = undefined;
    this.receiverReady = false;
    this.viewReady = false;
    this.setStatus(previewStartingMessage(this.runtime));
    const next = this.viewUrl(this.view, this.runtime);
    this.setPopoutUrl(next);
    this.navigatePreview(next);
  }

  private setPopoutUrl(url: string): void {
    this.state = { ...this.state, url };
    this.report(this.state);
  }

  private navigatePreview(next: string): void {
    const previewWindow = this.preview.contentWindow;
    try {
      if (previewWindow) {
        // Replace the child history entry before reloading so runtime changes
        // start a fresh adapter without adding navigation history.
        previewWindow.history.replaceState(previewWindow.history.state, "", next);
        previewWindow.location.reload();
        return;
      }
    } catch {
      // Initial and externally mounted frames navigate through the iframe.
    }
    this.preview.src = next;
  }

  private loaded(): void {
    if (this.receiverReady) {
      return;
    }
    const previewDocument = this.preview.contentDocument;
    const state = previewLoadState({
      hasRuntimeRoot: Boolean(previewDocument?.querySelector("#marimo-runtime-root")),
      documentState: previewDocument?.documentElement.dataset.marimoStudioPreviewState,
    });
    if (state === "ready") {
      this.scheduleRetry(10_000);
      return;
    }
    const repair = previewDocument?.querySelector<HTMLElement>("[data-marimo-studio-repair]");
    const detail = repair
      ? [repair.dataset.marimoStudioMessage, repair.dataset.marimoStudioHint]
          .filter(Boolean)
          .join(" ")
      : (previewDocument
          ?.querySelector<HTMLElement>("main, [role='status'], body > p")
          ?.textContent?.trim() ?? "");
    if (state === "waiting") {
      this.setStatus("Waiting for notebook", "loading", detail);
      return;
    }
    this.setStatus("Needs repair", "error", detail);
    this.scheduleRetry();
  }

  private readonly previewLoaded = (): void => {
    this.loaded();
    if (this.receiverReady && this.readyRevision) {
      this.beginControlSync(this.readyRevision);
    }
  };

  private readonly editorLoaded = (): void => {
    this.stopControlSync();
    if (this.receiverReady && this.readyRevision) {
      this.beginControlSync(this.readyRevision);
    }
  };

  private beginControlSync(revision: string): void {
    if (!this.connectControlFrame || this.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    if (
      (this.controlSync && this.controlSyncRevision === revision) ||
      this.controlSyncRequest?.revision === revision
    ) {
      return;
    }
    this.stopControlSync();
    this.controlSyncRetryAttempt = 0;
    void this.startControlSync(revision);
  }

  private async startControlSync(revision: string): Promise<void> {
    if (
      !this.connectControlFrame ||
      this.runtime === DEFAULT_RUNTIME_ID ||
      this.readyRevision !== revision
    ) {
      return;
    }
    if (this.controlSync || this.controlSyncRequest) {
      return;
    }
    const controller = new AbortController();
    const request = { controller, revision };
    this.controlSyncRequest = request;
    let retry = false;
    let failure: unknown;
    try {
      await previewReady(this.preview, controller.signal);
      if (controller.signal.aborted || this.controlSyncRequest !== request) {
        return;
      }
      const supportUrl = this.supportUrl(this.view);
      const [editorConfig, previewConfig] = await Promise.all([
        fetchRuntimeControls(supportUrl, DEFAULT_RUNTIME_ID, controller.signal),
        fetchRuntimeControls(supportUrl, this.runtime, controller.signal),
      ]);
      if (controller.signal.aborted || this.controlSyncRequest !== request) {
        return;
      }
      if (editorConfig.revision !== revision || editorConfig.revision !== previewConfig.revision) {
        retry = true;
        failure = new Error("Control configuration revisions have not converged");
        return;
      }
      if (!editorConfig.controls || !previewConfig.controls) {
        return;
      }
      const editor = this.connectControlFrame(this.editor);
      const preview = this.connectControlFrame(this.preview);
      if (!editor || !preview) {
        editor?.dispose();
        preview?.dispose();
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      const sync = await synchronizeControlEndpoints({
        editor,
        preview,
        editorControls: editorConfig.controls,
        previewControls: previewConfig.controls,
        signal: controller.signal,
      });
      if (
        controller.signal.aborted ||
        this.controlSyncRequest !== request ||
        this.readyRevision !== revision
      ) {
        sync.dispose();
        return;
      }
      this.controlSync = sync;
      this.controlSyncRevision = revision;
    } catch (error) {
      if (!controller.signal.aborted) {
        retry = true;
        failure = error;
      }
    } finally {
      if (this.controlSyncRequest === request) {
        this.controlSyncRequest = undefined;
      }
      if (retry && !controller.signal.aborted) {
        this.scheduleControlSync(revision, failure);
      }
    }
  }

  private scheduleControlSync(revision: string, failure?: unknown): void {
    if (
      this.readyRevision !== revision ||
      this.controlSyncRetryTimer !== undefined ||
      this.controlSyncRetryAttempt >= CONTROL_SYNC_RETRY_DELAYS.length
    ) {
      if (
        failure !== undefined &&
        this.controlSyncRetryAttempt >= CONTROL_SYNC_RETRY_DELAYS.length
      ) {
        console.warn("Marimo control state could not be synchronized", failure);
      }
      return;
    }
    const delay = CONTROL_SYNC_RETRY_DELAYS[this.controlSyncRetryAttempt];
    this.controlSyncRetryAttempt += 1;
    this.controlSyncRetryTimer = setTimeout(() => {
      this.controlSyncRetryTimer = undefined;
      void this.startControlSync(revision);
    }, delay);
  }

  private stopControlSync(): void {
    this.controlSyncRequest?.controller.abort();
    this.controlSyncRequest = undefined;
    this.controlSync?.dispose();
    this.controlSync = undefined;
    this.controlSyncRevision = undefined;
    if (this.controlSyncRetryTimer !== undefined) {
      clearTimeout(this.controlSyncRetryTimer);
      this.controlSyncRetryTimer = undefined;
    }
    this.controlSyncRetryAttempt = 0;
  }

  private showDiagnostics(): void {
    if (!this.diagnostics.length) {
      this.setStatus("Live", "ready");
      return;
    }
    const count = this.diagnostics.length;
    this.setStatus(
      `${count} ${count === 1 ? "issue" : "issues"}`,
      "warning",
      this.diagnostics.map((diagnostic) => diagnostic.message).join("\n"),
    );
  }

  private setStatus(
    message: string,
    state: "loading" | "ready" | "warning" | "error" = "loading",
    title = "",
  ): void {
    this.state = { ...this.state, status: { message, state, title } };
    this.report(this.state);
  }

  private scheduleRetry(delay = this.retrySchedule.next()): void {
    this.cancelRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      if (!this.receiverReady) {
        this.reload();
      }
    }, delay);
  }

  private cancelRetry(): void {
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
  }
}

const previewReady = async (frame: HTMLIFrameElement, signal: AbortSignal): Promise<void> => {
  const ready = (
    frame.contentWindow as (Window & { marimoStudio?: { ready(): Promise<void> } }) | null
  )?.marimoStudio?.ready;
  if (!ready) {
    return;
  }
  await Promise.race([
    ready(),
    new Promise<void>((resolve) =>
      signal.addEventListener("abort", () => resolve(), { once: true }),
    ),
  ]);
};
