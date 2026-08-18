import type {
  ObserveViewRequest,
  ShellChangeKind,
} from "@marimo-studio/protocol/development-events";

import {
  parsePreviewMessage,
  type PresentationToStudioMessage,
  type SourceChangeMessage,
  type SwitchViewMessage,
  type ViewDiagnostic,
  type ViewPreviewMessage,
} from "@marimo-studio/protocol/preview-messages";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

import type { ControlFrameConnector } from "./control-sync.ts";
import type { RecordBrowserObservation } from "./observation-remote.ts";
import type { EditorQuerySyncResult } from "./query-remote.ts";

import { assertNever } from "../../shared/assertNever.ts";
import { PreviewControlController } from "./control-controller.ts";
import { fetchRuntimeControls } from "./control-remote.ts";
import { PreviewObservationController } from "./observation-controller.ts";
import { PreviewQueryController } from "./query-controller.ts";
import { previewLoadState, RetrySchedule } from "./state.ts";
import { previewStartingMessage, type PreviewStatus } from "./status.ts";

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
  private readyRevision: string | undefined;
  private readySessionId: string | undefined;
  private pendingSourceRefresh = false;
  private sourceBaselineRevision: string | null | undefined;
  private readonly controls: PreviewControlController;
  private readonly observations: PreviewObservationController;
  private readonly queries: PreviewQueryController;

  constructor(
    initialView: string,
    private readonly runtime: string,
    private readonly editor: HTMLIFrameElement,
    private readonly preview: HTMLIFrameElement,
    private readonly viewUrl: (view: string, runtime: string) => string,
    private readonly supportUrl: (view: string) => string,
    syncQuery: (query: string) => void,
    syncEditorQuery: (
      query: string,
      operationId: string,
      signal: AbortSignal,
    ) => Promise<EditorQuerySyncResult>,
    private readonly navigate: (view: string) => void,
    private readonly report: (state: PreviewFrameState) => void,
    recordObservation?: RecordBrowserObservation,
    connectControlFrame?: ControlFrameConnector,
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
    this.controls = new PreviewControlController({
      runtime,
      editor,
      preview,
      supportUrl: () => this.supportUrl(this.view),
      connect: connectControlFrame,
      fetchControls: fetchRuntimeControls,
    });
    this.observations = new PreviewObservationController(runtime, preview, recordObservation);
    this.queries = new PreviewQueryController(runtime, preview, syncQuery, syncEditorQuery, () =>
      this.setPopoutUrl(this.viewUrl(this.view, this.runtime)),
    );
    this.bind();
  }

  switchView(view: string): void {
    this.controls.stop();
    this.readyRevision = undefined;
    this.readySessionId = undefined;
    delete this.preview.dataset.sessionId;
    this.viewReady = false;
    this.pendingSourceRefresh = true;
    this.sourceBaselineRevision = undefined;
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

  requestObservation(request: ObserveViewRequest): void {
    this.observations.request(request);
  }

  editorSessionChanged(): void {
    this.reload();
  }

  sourceChanged(kind: ShellChangeKind): void {
    this.sourceBaselineRevision = undefined;
    if (!this.receiverReady || !this.viewReady) {
      this.pendingSourceRefresh = true;
      return;
    }
    this.postSourceChange(kind);
  }

  sourceBaseline(revision: string | null): void {
    this.sourceBaselineRevision = revision ?? undefined;
    const needsRefresh =
      revision === null || (this.readyRevision !== undefined && this.readyRevision !== revision);
    if (!needsRefresh) {
      return;
    }
    this.pendingSourceRefresh = true;
    if (this.receiverReady && this.viewReady) {
      this.pendingSourceRefresh = false;
      this.postSourceChange("html");
    }
  }

  private postSourceChange(kind: ShellChangeKind): void {
    const message: SourceChangeMessage = {
      type: "marimo-studio:source-change",
      runtime: this.runtime,
      view: this.view,
      kind,
    };
    this.preview.contentWindow?.postMessage(message, globalThis.location.origin);
  }

  editorQueryChanged(query: string, operationId?: string, completed = false): void {
    this.queries.editorChanged(query, this.viewReady, operationId, completed);
  }

  dispose(): void {
    this.cancelRetry();
    this.controls.stop();
    this.queries.cancel();
    this.observations.clear();
    this.editor.removeEventListener("load", this.startFromEditor);
    this.preview.removeEventListener("load", this.previewLoaded);
    globalThis.removeEventListener("message", this.message);
  }

  private bind(): void {
    globalThis.addEventListener("message", this.message);
    this.preview.addEventListener("load", this.previewLoaded);
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
    const payload = jsonValueSchema.safeParse(event.data);
    if (!payload.success) {
      return;
    }
    const message = parsePreviewMessage(payload.data);
    if (
      !message ||
      message.type === "marimo-studio:switch-view" ||
      message.type === "marimo-studio:source-change" ||
      message.type === "marimo-studio:observe-view" ||
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
      case "marimo-studio:receiver-unready":
        this.controls.stop();
        this.readyRevision = undefined;
        this.readySessionId = undefined;
        delete this.preview.dataset.sessionId;
        this.receiverReady = false;
        this.viewReady = false;
        this.pendingSourceRefresh = true;
        return;
      case "marimo-studio:receiver-ready":
        this.controls.stop();
        this.readyRevision = undefined;
        this.readySessionId = undefined;
        delete this.preview.dataset.sessionId;
        this.receiverReady = true;
        this.viewReady = false;
        this.cancelRetry();
        this.retrySchedule.reset();
        if (message.view === this.view) {
          this.setStatus(previewStartingMessage(this.runtime));
          if (this.pendingSourceRefresh && this.sourceBaselineRevision === undefined) {
            this.pendingSourceRefresh = false;
            this.postSourceChange("html");
          }
        } else {
          this.pendingSourceRefresh = true;
          this.postSwitch();
        }
        this.observations.post();
        return;
      case "marimo-studio:view-ready":
      case "marimo-studio:view-sync-pending":
      case "marimo-studio:view-diagnostics":
      case "marimo-studio:view-error":
      case "marimo-studio:view-observation":
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
        this.readySessionId = message.sessionId;
        if (message.sessionId === undefined) {
          delete this.preview.dataset.sessionId;
        } else {
          this.preview.dataset.sessionId = message.sessionId;
        }
        this.readyRevision = message.revision;
        this.viewReady = true;
        if (this.sourceBaselineRevision !== undefined) {
          this.pendingSourceRefresh = this.sourceBaselineRevision !== message.revision;
        }
        this.showDiagnostics();
        this.controls.begin(message.revision, message.sessionId);
        void this.queries.applyToPreview(this.viewReady);
        this.observations.post();
        if (this.pendingSourceRefresh) {
          this.pendingSourceRefresh = false;
          this.postSourceChange("html");
        }
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
      case "marimo-studio:view-observation":
        this.observations.receive(message);
        this.readyRevision = message.revision;
        this.viewReady = message.state === "ready";
        this.diagnostics = message.diagnostics;
        if (message.state === "ready") {
          this.showDiagnostics();
        } else if (message.state === "loading") {
          this.setStatus("Waiting for rendered view", "loading");
        } else {
          this.setStatus(
            "Needs repair",
            "error",
            message.diagnostics.map((diagnostic) => diagnostic.message).join("\n"),
          );
        }
        return;
      default:
        assertNever(message);
    }
  }

  private previewQueryChanged(query: string): void {
    this.queries.previewChanged(query);
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
    this.controls.stop();
    this.queries.cancel();
    this.readyRevision = undefined;
    this.readySessionId = undefined;
    delete this.preview.dataset.sessionId;
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
      this.controls.begin(this.readyRevision, this.readySessionId);
    }
  };

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
