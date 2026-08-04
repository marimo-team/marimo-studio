import type { ControlFrameConnector } from "./control-sync.ts";

import { observeFrameQuery } from "../query-sync.ts";
import { PreviewController, type PreviewFrameState, type PreviewStatus } from "./controller.ts";
import { installEditorOutlineGuard } from "./editor-outline.ts";

interface PreviewDeckOptions {
  initialView: string;
  initialRuntime: string;
  runtimes: readonly string[];
  editor: HTMLIFrameElement;
  preview: HTMLIFrameElement;
  popouts: readonly HTMLAnchorElement[];
  statuses: readonly HTMLElement[];
  viewUrl: (view: string, runtime: string) => string;
  supportUrl: (view: string) => string;
  syncQuery: (query: string) => void;
  syncEditorQuery: (query: string, signal: AbortSignal) => Promise<void>;
  navigate: (view: string) => void;
  connectControlFrame?: ControlFrameConnector;
}

interface PreviewRuntime {
  controller: PreviewController;
  frame: HTMLIFrameElement;
  state: PreviewFrameState;
  created: boolean;
}

const startingStatus = (runtime: string): PreviewStatus => ({
  message: runtime === "wasm" ? "Starting WebAssembly" : "Connecting to server",
  state: "loading",
  title: "",
});

export class PreviewDeck {
  private readonly previews = new Map<string, PreviewRuntime>();
  private runtime: string;
  private view: string;
  private stopEditorQuerySync: (() => void) | undefined;
  private stopEditorOutlineGuard: (() => void) | undefined;

  constructor(private readonly options: PreviewDeckOptions) {
    this.runtime = options.initialRuntime;
    this.view = options.initialView;
    this.ensure(options.initialRuntime, options.preview);
    this.activate(options.initialRuntime);
    if (options.runtimes.includes("wasm") && options.initialRuntime !== "wasm") {
      this.ensure("wasm");
    }
    this.bindEditor();
  }

  switchRuntime(runtime: string): void {
    if (runtime === this.runtime || !this.options.runtimes.includes(runtime)) {
      return;
    }
    this.activate(runtime);
  }

  switchView(view: string): void {
    this.view = view;
    this.previews.forEach(({ controller }) => controller.switchView(view));
  }

  requestResize(): void {
    this.options.editor.contentWindow?.dispatchEvent(new Event("resize"));
    this.previews.forEach(({ controller }) => controller.requestResize());
  }

  dispose(): void {
    this.stopEditorQuerySync?.();
    this.stopEditorOutlineGuard?.();
    this.options.editor.removeEventListener("load", this.editorLoaded);
    this.previews.forEach(({ controller, frame, created }) => {
      controller.dispose();
      if (created) {
        frame.remove();
      }
    });
    this.previews.clear();
  }

  private bindEditor(): void {
    this.guardEditorOutline();
    this.options.editor.addEventListener("load", this.editorLoaded);
    this.stopEditorQuerySync = observeFrameQuery(this.options.editor, (query) => {
      this.previews.forEach(({ controller }) => controller.editorQueryChanged(query));
    });
  }

  private readonly editorLoaded = (): void => {
    this.guardEditorOutline();
  };

  private guardEditorOutline(): void {
    this.stopEditorOutlineGuard?.();
    this.stopEditorOutlineGuard = undefined;
    const editorDocument = this.options.editor.contentDocument;
    if (editorDocument) {
      this.stopEditorOutlineGuard = installEditorOutlineGuard(editorDocument);
    }
  }

  private ensure(runtime: string, frame?: HTMLIFrameElement): PreviewRuntime {
    const existing = this.previews.get(runtime);
    if (existing) {
      return existing;
    }
    const target = frame ?? this.createFrame();
    target.dataset.previewRuntimeFrame = runtime;
    target.title = `${this.view} custom view using ${runtime}`;
    const initialState: PreviewFrameState = {
      url: this.options.viewUrl(this.view, runtime),
      status: startingStatus(runtime),
    };
    const entry: PreviewRuntime = {
      frame: target,
      state: initialState,
      created: target !== this.options.preview,
      controller: new PreviewController(
        this.view,
        runtime,
        this.options.editor,
        target,
        this.options.viewUrl,
        this.options.supportUrl,
        this.options.syncQuery,
        this.options.syncEditorQuery,
        this.options.navigate,
        (state) => this.receive(runtime, state),
        this.options.connectControlFrame,
      ),
    };
    this.previews.set(runtime, entry);
    return entry;
  }

  private createFrame(): HTMLIFrameElement {
    const frame = this.options.preview.cloneNode(false) as HTMLIFrameElement;
    frame.removeAttribute("data-session-id");
    frame.src = "about:blank";
    frame.hidden = true;
    frame.inert = true;
    this.options.preview.parentElement?.append(frame);
    return frame;
  }

  private activate(runtime: string): void {
    const selected = this.ensure(runtime);
    this.runtime = runtime;
    this.previews.forEach(({ frame }, candidate) => {
      const active = candidate === runtime;
      frame.hidden = !active;
      frame.inert = !active;
    });
    this.render(selected.state);
    selected.controller.requestResize();
  }

  private receive(runtime: string, state: PreviewFrameState): void {
    const preview = this.previews.get(runtime);
    if (!preview) {
      return;
    }
    preview.state = state;
    if (runtime === this.runtime) {
      this.render(state);
    }
  }

  private render({ url, status }: PreviewFrameState): void {
    this.options.popouts.forEach((popout) => {
      popout.href = url;
    });
    this.options.statuses.forEach((target) => {
      target.textContent = status.message;
      target.dataset.state = status.state;
      const detail = status.title ? `${status.message}: ${status.title}` : status.message;
      target.closest<HTMLElement>("[data-runtime-trigger]")?.setAttribute("title", detail);
      if (status.title) {
        target.title = status.title;
      } else {
        target.removeAttribute("title");
      }
    });
  }
}
