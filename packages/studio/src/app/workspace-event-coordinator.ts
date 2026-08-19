import {
  parseActiveViewRequest,
  parseEditorSessionBinding,
  parseObserveViewRequest,
  parseShellChange,
  type EditorSessionBinding,
  type ActiveViewRequest,
  type ObserveViewRequest,
  type ShellChangeKind,
} from "@marimo-studio/protocol/development-events";
import {
  parseSourceBaseline,
  parseSourceChanges,
  type SourceFileChange,
} from "@marimo-studio/protocol/source-events";

import type { ViewLanding } from "../features/views/transition.ts";
import type { AcknowledgeViewActivation } from "./activation-remote.ts";

interface WorkspaceViewPort {
  subscribe(listener: () => void): () => void;
  getSnapshot(): { current: string };
  refreshInventory(): Promise<void>;
  ensureAvailable(view: string): Promise<boolean>;
  choose(view: string, landing: ViewLanding): Promise<boolean>;
}

interface WorkspacePreviewPort {
  requestObservation(request: ObserveViewRequest): void;
  editorSessionChanged(binding: EditorSessionBinding): void;
  reload(): void;
  sourceBaseline(revision: string | null): void;
  sourceChanged(kind: ShellChangeKind): void;
}

interface WorkspaceSourcePort {
  reconcile(): void;
  externalChanges(changes: readonly SourceFileChange[]): void;
}

interface WorkspaceEventCoordinatorOptions {
  eventsUrl: string;
  views: WorkspaceViewPort;
  preview: WorkspacePreviewPort;
  source: WorkspaceSourcePort;
  acknowledge: AcknowledgeViewActivation;
}

export class WorkspaceEventCoordinator {
  private readonly lifecycle = new AbortController();
  private events: EventSource | undefined;
  private stopViews: (() => void) | undefined;
  private connectionGeneration = 0;
  private currentView: string;
  private acknowledgedActivation = -1;
  private readonly activationInFlight = new Set<number>();
  private started = false;
  private disposed = false;

  constructor(private readonly options: WorkspaceEventCoordinatorOptions) {
    this.currentView = options.views.getSnapshot().current;
  }

  start(initialActivation?: ActiveViewRequest): void {
    if (this.started || this.disposed) {
      return;
    }
    this.started = true;
    this.stopViews = this.options.views.subscribe(this.viewChanged);
    this.connect();
    if (initialActivation) {
      this.requestActivation(initialActivation, false);
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.lifecycle.abort();
    this.stopViews?.();
    this.stopViews = undefined;
    this.connectionGeneration += 1;
    this.events?.close();
    this.events = undefined;
  }

  private readonly viewChanged = (): void => {
    const view = this.options.views.getSnapshot().current;
    if (view === this.currentView) {
      return;
    }
    this.currentView = view;
    this.connect();
  };

  private connect(): void {
    const generation = ++this.connectionGeneration;
    this.events?.close();
    const url = new URL(this.options.eventsUrl, globalThis.location.href);
    url.searchParams.set("marimo_studio_view", this.currentView);
    const events = new EventSource(url.href);
    this.events = events;
    const current = (operation: () => void) => {
      if (this.disposed || this.events !== events || generation !== this.connectionGeneration) {
        return;
      }
      operation();
    };
    events.addEventListener("ready", (event) =>
      current(() => {
        this.refreshInventory();
        this.options.source.reconcile();
        const baseline = parseSourceBaseline(this.data(event));
        this.options.preview.sourceBaseline(
          baseline?.view === this.currentView ? baseline.revision : null,
        );
      }),
    );
    events.addEventListener("change", (event) =>
      current(() => this.sourceChanged(this.data(event))),
    );
    events.addEventListener("activate", (event) =>
      current(() => {
        const payload = parseActiveViewRequest(this.data(event));
        if (payload) {
          this.requestActivation(payload, true);
        }
      }),
    );
    events.addEventListener("observe", (event) =>
      current(() => {
        const request = parseObserveViewRequest(this.data(event));
        if (request) {
          void this.observe(request);
        }
      }),
    );
    events.addEventListener("session", (event) =>
      current(() => {
        const binding = parseEditorSessionBinding(this.data(event));
        if (binding) {
          this.options.preview.editorSessionChanged(binding);
        }
      }),
    );
  }

  private readonly refreshInventory = (): void => {
    void this.options.views.refreshInventory().catch((cause: unknown) => {
      if (!this.disposed) {
        console.warn("Studio views could not be refreshed", cause);
      }
    });
  };

  private sourceChanged(data: string): void {
    this.refreshInventory();
    this.options.source.externalChanges(parseSourceChanges(data));
    const kind = parseShellChange(data);
    if (kind) {
      this.options.preview.sourceChanged(kind);
    }
  }

  private requestActivation(request: ActiveViewRequest, reloadActive: boolean): void {
    if (
      request.generation <= this.acknowledgedActivation ||
      this.activationInFlight.has(request.generation)
    ) {
      return;
    }
    this.activationInFlight.add(request.generation);
    void this.activate(request.view, request.generation, reloadActive).then((acknowledged) => {
      this.activationInFlight.delete(request.generation);
      if (acknowledged) {
        this.acknowledgedActivation = Math.max(this.acknowledgedActivation, request.generation);
      } else if (!this.disposed) {
        this.connect();
      }
    });
  }

  private async activate(
    view: string,
    generation: number,
    reloadActive: boolean,
  ): Promise<boolean> {
    try {
      if (!(await this.options.views.ensureAvailable(view))) {
        return false;
      }
      const alreadyActive = this.options.views.getSnapshot().current === view;
      if (
        !(await this.options.views.choose(view, "split")) ||
        this.disposed ||
        this.options.views.getSnapshot().current !== view
      ) {
        return false;
      }
      if (alreadyActive && reloadActive) {
        this.options.preview.reload();
      }
      await this.options.acknowledge(generation, view, this.lifecycle.signal);
      return true;
    } catch (error) {
      if (!this.disposed) {
        console.warn("Studio view could not be activated", error);
      }
      return false;
    }
  }

  private async observe(request: ObserveViewRequest): Promise<void> {
    try {
      if (request.activeViewGeneration !== undefined) {
        if (!this.disposed && this.options.views.getSnapshot().current === request.view) {
          this.options.preview.requestObservation(request);
        }
        return;
      }
      if (
        (await this.options.views.ensureAvailable(request.view)) &&
        (await this.options.views.choose(request.view, "preserve")) &&
        !this.disposed &&
        this.options.views.getSnapshot().current === request.view
      ) {
        this.options.preview.requestObservation(request);
      }
    } catch (error) {
      if (!this.disposed) {
        console.warn("Studio view could not be prepared for browser analysis", error);
      }
    }
  }

  private data(event: Event): string {
    return event instanceof MessageEvent ? String(event.data) : "";
  }
}
