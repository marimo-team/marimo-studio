import {
  previewLoadState,
  RefreshRetrySchedule,
} from "../shell-refresh-state.ts";
import { observeFrameQuery } from "../query-sync.ts";

interface ViewDiagnostic {
  message: string;
}

export class PreviewController {
  private view: string;
  private receiverReady = false;
  private diagnostics: ViewDiagnostic[] = [];
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RefreshRetrySchedule();
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
    this.stopEditorQuerySync = observeFrameQuery(
      this.editor,
      (query) => this.editorQueryChanged(query),
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
    const data = event.data;
    if (typeof data !== "object" || data === null || !("type" in data)) {
      return;
    }
    if (
      data.type === "marimo-studio:navigate-view" &&
      "view" in data &&
      typeof data.view === "string"
    ) {
      this.navigate(data.view);
      return;
    }
    if (
      data.type === "marimo-studio:query-change" &&
      "query" in data &&
      typeof data.query === "string"
    ) {
      this.queryChanged(data.query);
      return;
    }
    if (data.type === "marimo-studio:receiver-ready") {
      this.receiverReady = true;
      this.cancelRetry();
      this.retrySchedule.reset();
      const active = "view" in data && typeof data.view === "string"
        ? data.view
        : undefined;
      if (active === this.view) {
        this.showDiagnostics();
      } else {
        this.postSwitch();
      }
      return;
    }
    if (
      !("view" in data) ||
      typeof data.view !== "string" ||
      data.view !== this.view
    ) {
      return;
    }
    if (data.type === "marimo-studio:view-ready") {
      if ("sessionId" in data && typeof data.sessionId === "string") {
        this.preview.dataset.sessionId = data.sessionId;
      }
      this.showDiagnostics();
    } else if (
      data.type === "marimo-studio:view-sync-pending" &&
      "message" in data &&
      typeof data.message === "string"
    ) {
      this.setStatus(
        "Waiting for notebook",
        "loading",
        "hint" in data && typeof data.hint === "string"
          ? data.hint
          : data.message,
      );
    } else if (
      data.type === "marimo-studio:view-diagnostics" &&
      "diagnostics" in data &&
      Array.isArray(data.diagnostics) &&
      data.diagnostics.every((diagnostic) =>
        typeof diagnostic === "object" &&
        diagnostic !== null &&
        "message" in diagnostic &&
        typeof diagnostic.message === "string"
      )
    ) {
      this.diagnostics = data.diagnostics as ViewDiagnostic[];
      this.showDiagnostics();
    } else if (
      data.type === "marimo-studio:view-error" &&
      "message" in data &&
      typeof data.message === "string"
    ) {
      this.setStatus(
        "Needs repair",
        "error",
        "hint" in data && typeof data.hint === "string"
          ? data.hint
          : data.message,
      );
    }
  };

  private queryChanged(query: string): void {
    this.syncQuery(query);
    this.popout.href = this.viewUrl(this.view);
  }

  private editorQueryChanged(query: string): void {
    this.queryChanged(query);
    if (
      !this.receiverReady &&
      this.preview.src !== "about:blank" &&
      this.preview.src !==
        new URL(this.viewUrl(this.view), globalThis.location.href).href
    ) {
      this.reload();
    }
  }

  private postSwitch(): void {
    this.preview.contentWindow?.postMessage(
      {
        type: "marimo-studio:switch-view",
        view: this.view,
        documentUrl: this.viewUrl(this.view),
        supportUrl: this.supportUrl(this.view),
      },
      globalThis.location.origin,
    );
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
      hasRuntimeRoot: Boolean(
        previewDocument?.querySelector("#marimo-runtime-root"),
      ),
      documentState: previewDocument?.documentElement.dataset
        .marimoStudioPreviewState,
    });
    if (state === "ready") {
      this.scheduleRetry(10_000);
      return;
    }
    const repair = previewDocument?.querySelector<HTMLElement>(
      "[data-marimo-studio-repair]",
    );
    const detail = repair
      ? [repair.dataset.marimoStudioMessage, repair.dataset.marimoStudioHint]
        .filter(Boolean)
        .join(" ")
      : previewDocument?.querySelector<HTMLElement>(
        "main, [role='status'], body > p",
      )?.textContent?.trim() ?? "";
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
