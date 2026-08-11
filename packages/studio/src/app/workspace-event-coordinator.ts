import {
  parseActiveViewRequest,
  parseEditorSessionBinding,
  parseObserveViewRequest,
  type EditorSessionBinding,
  type ObserveViewRequest,
} from "@marimo-studio/protocol/development-events";

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
}

interface WorkspaceEventCoordinatorOptions {
  eventsUrl: string;
  views: WorkspaceViewPort;
  preview: WorkspacePreviewPort;
  acknowledge: AcknowledgeViewActivation;
}

export class WorkspaceEventCoordinator {
  private readonly lifecycle = new AbortController();
  private events: EventSource | undefined;
  private stopViews: (() => void) | undefined;
  private connectionGeneration = 0;
  private currentView: string;
  private started = false;
  private disposed = false;

  constructor(private readonly options: WorkspaceEventCoordinatorOptions) {
    this.currentView = options.views.getSnapshot().current;
  }

  start(): void {
    if (this.started || this.disposed) {
      return;
    }
    this.started = true;
    this.stopViews = this.options.views.subscribe(this.viewChanged);
    this.connect();
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
    events.addEventListener("ready", () => current(this.refreshInventory));
    events.addEventListener("change", () => current(this.refreshInventory));
    events.addEventListener("activate", (event) =>
      current(() => {
        const payload = parseActiveViewRequest(this.data(event));
        if (payload) {
          void this.activate(payload.view, payload.generation);
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
    void this.options.views.refreshInventory().catch((error: unknown) => {
      if (!this.disposed) {
        console.warn("Studio views could not be refreshed", error);
      }
    });
  };

  private async activate(view: string, generation: number): Promise<void> {
    try {
      if (
        !(await this.options.views.ensureAvailable(view)) ||
        !(await this.options.views.choose(view, "preserve")) ||
        this.disposed ||
        this.options.views.getSnapshot().current !== view
      ) {
        return;
      }
      await this.options.acknowledge(generation, view, this.lifecycle.signal);
    } catch (error) {
      if (!this.disposed) {
        console.warn("Studio view could not be activated", error);
      }
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
