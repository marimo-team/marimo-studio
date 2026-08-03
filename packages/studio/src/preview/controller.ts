import {
  parsePreviewMessage,
  type PresentationToStudioMessage,
  type SwitchViewMessage,
  type ViewDiagnostic,
  type ViewPreviewMessage,
} from "@marimo-studio/protocol/preview-messages";

import { observeFrameQuery } from "../query-sync.ts";
import { previewLoadState, RetrySchedule } from "./state.ts";

export class PreviewController {
  private view: string;
  private receiverReady = false;
  private diagnostics: ViewDiagnostic[] = [];
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RetrySchedule();
  private stopEditorQuerySync: (() => void) | undefined;

  constructor(
    initialView: string,
    private readonly editor: HTMLIFrameElement,
    private readonly preview: HTMLIFrameElement,
    private readonly popout: HTMLAnchorElement,
    private readonly status: HTMLElement,
    private readonly viewUrl: (view: string) => string,
    private readonly supportUrl: (view: string) => string,
    private readonly syncQuery: (query: string) => void,
    private readonly navigate: (view: string) => void,
  ) {
    this.view = initialView;
    this.bind();
  }

  switchView(view: string): void {
    this.view = view;
    const nextPreview = this.viewUrl(view);
    this.preview.title = `${view} custom view`;
    this.popout.href = nextPreview;
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
    this.editor.contentWindow?.dispatchEvent(new Event("resize"));
  }

  dispose(): void {
    this.cancelRetry();
    this.stopEditorQuerySync?.();
    globalThis.removeEventListener("message", this.message);
  }

  private bind(): void {
    globalThis.addEventListener("message", this.message);
    this.preview.addEventListener("load", () => this.loaded());
    this.stopEditorQuerySync = observeFrameQuery(this.editor, (query) =>
      this.editorQueryChanged(query),
    );
    const start = () => {
      if (this.preview.src === "about:blank") {
        this.reload();
      }
    };
    this.editor.addEventListener("load", start, { once: true });
    if (this.editor.contentDocument?.readyState === "complete") {
      start();
    }
  }

  private readonly message = (event: MessageEvent<unknown>) => {
    if (
      event.origin !== globalThis.location.origin ||
      event.source !== this.preview.contentWindow
    ) {
      return;
    }
    const message = parsePreviewMessage(event.data);
    if (!message || message.type === "marimo-studio:switch-view") {
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
        this.queryChanged(message.query);
        return;
      case "marimo-studio:receiver-ready":
        this.receiverReady = true;
        this.cancelRetry();
        this.retrySchedule.reset();
        if (message.view === this.view) {
          this.showDiagnostics();
        } else {
          this.postSwitch();
        }
        return;
      default:
        if (message.view === this.view) {
          this.receiveView(message);
        }
    }
  }

  private receiveView(message: ViewPreviewMessage): void {
    switch (message.type) {
      case "marimo-studio:view-ready":
        if (message.sessionId !== undefined) {
          this.preview.dataset.sessionId = message.sessionId;
        }
        this.showDiagnostics();
        return;
      case "marimo-studio:view-sync-pending":
        this.setStatus("Waiting for notebook", "loading", message.hint);
        return;
      case "marimo-studio:view-diagnostics":
        this.diagnostics = message.diagnostics;
        this.showDiagnostics();
        return;
      case "marimo-studio:view-error":
        this.setStatus("Needs repair", "error", message.hint);
    }
  }

  private queryChanged(query: string): void {
    this.syncQuery(query);
    this.popout.href = this.viewUrl(this.view);
  }

  private editorQueryChanged(query: string): void {
    this.queryChanged(query);
    if (
      !this.receiverReady &&
      this.preview.src !== "about:blank" &&
      this.preview.src !== new URL(this.viewUrl(this.view), globalThis.location.href).href
    ) {
      this.reload();
    }
  }

  private postSwitch(): void {
    const message: SwitchViewMessage = {
      type: "marimo-studio:switch-view",
      view: this.view,
      documentUrl: this.viewUrl(this.view),
      supportUrl: this.supportUrl(this.view),
    };
    this.preview.contentWindow?.postMessage(message, globalThis.location.origin);
  }

  private reload(): void {
    this.cancelRetry();
    this.receiverReady = false;
    this.setStatus("Connecting");
    this.preview.src = this.viewUrl(this.view);
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
    this.status.textContent = message;
    this.status.dataset.state = state;
    if (title) {
      this.status.title = title;
    } else {
      this.status.removeAttribute("title");
    }
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
