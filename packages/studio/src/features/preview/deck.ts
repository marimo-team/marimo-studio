import type { ControlFrameConnector } from "./control-sync.ts";
import type { RecordBrowserObservation } from "./observation-remote.ts";

import { PreviewController, type PreviewFrameState } from "./controller.ts";
import { installEditorOutlineGuard } from "./editor-outline.ts";
import { observeFrameQuery } from "./query-sync.ts";
import { previewStartingStatus } from "./status.ts";

interface PreviewDeckOptions {
  initialView: string;
  initialRuntime: string;
  runtimes: readonly string[];
  viewUrl: (view: string, runtime: string) => string;
  supportUrl: (view: string) => string;
  syncQuery: (query: string) => void;
  syncEditorQuery: (query: string, signal: AbortSignal) => Promise<void>;
  navigate: (view: string) => void;
  recordObservation?: RecordBrowserObservation;
  connectControlFrame?: ControlFrameConnector;
}

export interface PreviewDeckSnapshot {
  runtime: string;
  states: Readonly<Record<string, PreviewFrameState>>;
}

type Listener = () => void;

export class PreviewDeck {
  private readonly previews = new Map<string, PreviewController>();
  private readonly listeners = new Set<Listener>();
  private readonly states = new Map<string, PreviewFrameState>();
  private runtime: string;
  private view: string;
  private editor: HTMLIFrameElement | undefined;
  private frames: ReadonlyMap<string, HTMLIFrameElement> | undefined;
  private snapshot!: PreviewDeckSnapshot;
  private stopEditorQuerySync: (() => void) | undefined;
  private stopEditorOutlineGuard: (() => void) | undefined;

  constructor(private readonly options: PreviewDeckOptions) {
    this.runtime = options.initialRuntime;
    this.view = options.initialView;
    for (const runtime of options.runtimes) {
      this.states.set(runtime, {
        url: options.viewUrl(this.view, runtime),
        status: previewStartingStatus(runtime),
      });
    }
    this.updateSnapshot();
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): PreviewDeckSnapshot => this.snapshot;

  attach(editor: HTMLIFrameElement, frames: ReadonlyMap<string, HTMLIFrameElement>): void {
    if (this.editor) {
      return;
    }
    this.editor = editor;
    this.frames = frames;
    this.ensure(this.runtime);
    if (this.options.runtimes.includes("wasm") && this.runtime !== "wasm") {
      this.ensure("wasm");
    }
    this.bindEditor();
  }

  switchRuntime(runtime: string): void {
    if (runtime === this.runtime || !this.options.runtimes.includes(runtime)) {
      return;
    }
    this.ensure(runtime);
    this.runtime = runtime;
    this.publish();
    this.previews.get(runtime)?.requestResize();
  }

  switchView(view: string): void {
    this.view = view;
    for (const runtime of this.options.runtimes) {
      if (!this.previews.has(runtime)) {
        this.states.set(runtime, {
          url: this.options.viewUrl(view, runtime),
          status: previewStartingStatus(runtime),
        });
      }
    }
    this.previews.forEach((controller) => controller.switchView(view));
    this.publish();
  }

  requestResize(): void {
    this.editor?.contentWindow?.dispatchEvent(new Event("resize"));
    this.previews.forEach((controller) => controller.requestResize());
  }

  dispose(): void {
    this.stopEditorQuerySync?.();
    this.stopEditorOutlineGuard?.();
    this.editor?.removeEventListener("load", this.editorLoaded);
    this.previews.forEach((controller) => controller.dispose());
    this.previews.clear();
    this.listeners.clear();
  }

  private bindEditor(): void {
    const editor = this.editor;
    if (!editor) {
      return;
    }
    this.guardEditorOutline();
    editor.addEventListener("load", this.editorLoaded);
    this.stopEditorQuerySync = observeFrameQuery(editor, (query) => {
      this.previews.forEach((controller) => controller.editorQueryChanged(query));
    });
  }

  private readonly editorLoaded = (): void => {
    this.guardEditorOutline();
  };

  private guardEditorOutline(): void {
    this.stopEditorOutlineGuard?.();
    this.stopEditorOutlineGuard = undefined;
    const editorDocument = this.editor?.contentDocument;
    if (editorDocument) {
      this.stopEditorOutlineGuard = installEditorOutlineGuard(editorDocument);
    }
  }

  private ensure(runtime: string): PreviewController | undefined {
    const existing = this.previews.get(runtime);
    if (existing) {
      return existing;
    }
    const editor = this.editor;
    const frame = this.frames?.get(runtime);
    if (!editor || !frame) {
      return undefined;
    }
    const controller = new PreviewController(
      this.view,
      runtime,
      editor,
      frame,
      this.options.viewUrl,
      this.options.supportUrl,
      this.options.syncQuery,
      this.options.syncEditorQuery,
      this.options.navigate,
      (state) => this.receive(runtime, state),
      this.options.recordObservation,
      this.options.connectControlFrame,
    );
    this.previews.set(runtime, controller);
    return controller;
  }

  private receive(runtime: string, state: PreviewFrameState): void {
    if (!this.states.has(runtime)) {
      return;
    }
    this.states.set(runtime, state);
    this.publish();
  }

  private publish(): void {
    this.updateSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private updateSnapshot(): void {
    this.snapshot = {
      runtime: this.runtime,
      states: Object.fromEntries(this.states),
    };
  }
}
