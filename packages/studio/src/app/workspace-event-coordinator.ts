import {
  parseActiveViewRequest,
  parseEditorSessionBinding,
  parseObserveViewRequest,
  parsePresentationBuild,
  parsePresentationChange,
  parseWorkspaceChange,
  type EditorSessionBinding,
  type ActiveViewRequest,
  type ObserveViewRequest,
} from "@marimo-studio/protocol/development-events";
import { WORKSPACE_STREAM_QUERY_PARAM } from "@marimo-studio/protocol/query";
import {
  parsePresentationBaseline,
  parseSourceChanges,
  type SourceFileChange,
} from "@marimo-studio/protocol/source-events";

import type { ViewLanding, ViewSelectionOwner } from "../features/views/transition.ts";

import {
  type AcknowledgeViewActivation,
  ViewActivationAcknowledgementError,
} from "./activation-remote.ts";

interface WorkspaceViewPort {
  subscribe(listener: () => void): () => void;
  getSnapshot(): { current: string };
  refreshInventory(): Promise<void>;
  ensureAvailable(view: string, signal?: AbortSignal): Promise<boolean>;
  choose(
    view: string,
    landing: ViewLanding,
    navigation?: undefined,
    signal?: AbortSignal,
    owner?: ViewSelectionOwner,
  ): Promise<boolean>;
  cancelPendingSelection(): void;
}

interface WorkspacePreviewPort {
  requestObservation(request: ObserveViewRequest): void;
  editorSessionChanged(binding: EditorSessionBinding): void;
  reload(): void;
  presentationBaseline(view: string, revision: string | null): void;
  presentationBuildStarted(view: string, notebookMutationGeneration?: number): void;
  presentationBuildCompleted(
    view: string,
    revision: string | null,
    notebookMutationGeneration?: number,
  ): void;
  presentationStreamAbandoned(view: string): void;
  presentationChanged(view: string, revision: string): void;
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

const ACTIVATION_TRANSITION_TIMEOUT_MS = 110_000;
const ACTIVE_VIEW_RECOVERY_TIMEOUT_MS = 10_000;
let issuedStreamGeneration = 0;

export const workspaceEventsUrl = (eventsUrl: string, activeView?: string): string => {
  issuedStreamGeneration = Math.max(issuedStreamGeneration + 1, Date.now());
  const url = new URL(eventsUrl, globalThis.location.href);
  url.searchParams.set(WORKSPACE_STREAM_QUERY_PARAM, String(issuedStreamGeneration));
  if (activeView !== undefined) {
    url.searchParams.set("marimo_studio_view", activeView);
  }
  return url.href;
};

export class WorkspaceEventCoordinator {
  private events: EventSource | undefined;
  private pendingEvents: EventSource | undefined;
  private stopViews: (() => void) | undefined;
  private connectionGeneration = 0;
  private currentView: string;
  private acknowledgedActivation = -1;
  private latestActivation = -1;
  private activationAbort: AbortController | undefined;
  private readonly activationInFlight = new Set<number>();
  private notebookMutationGeneration: number | undefined;
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
    this.activationAbort?.abort();
    this.activationAbort = undefined;
    this.stopViews?.();
    this.stopViews = undefined;
    this.connectionGeneration += 1;
    this.pendingEvents?.close();
    this.pendingEvents = undefined;
    this.events?.close();
    this.events = undefined;
  }

  async recoverActiveView(view: string, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted();
    if (
      this.disposed ||
      !this.started ||
      view !== this.currentView ||
      view !== this.options.views.getSnapshot().current
    ) {
      throw new Error("The committed Studio view changed before recovery.");
    }
    this.pendingEvents?.close();
    this.pendingEvents = undefined;
    this.events?.close();
    this.events = undefined;
    const owner = new AbortController();
    const cancel = () => owner.abort(signal.reason);
    signal.addEventListener("abort", cancel, { once: true });
    const timeout = setTimeout(
      () => owner.abort(new DOMException("Active view recovery timed out", "TimeoutError")),
      ACTIVE_VIEW_RECOVERY_TIMEOUT_MS,
    );
    try {
      await abortable(new Promise<void>((resolve) => this.connect(view, resolve)), owner.signal);
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener("abort", cancel);
    }
  }

  reconcileNotebookMutation(generation: number): void {
    if (!this.started || this.disposed) {
      return;
    }
    this.notebookMutationGeneration = generation;
    this.connect(undefined, undefined, generation);
  }

  reconcileEditorReload(): void {
    if (!this.started || this.disposed) {
      return;
    }
    this.notebookMutationGeneration = undefined;
    this.connect();
  }

  private readonly viewChanged = (): void => {
    const view = this.options.views.getSnapshot().current;
    if (view === this.currentView) {
      return;
    }
    const previousView = this.currentView;
    this.currentView = view;
    this.connect(previousView, undefined, this.notebookMutationGeneration);
  };

  private connect(
    abandonedView?: string,
    connectionReady?: () => void,
    notebookMutationGeneration?: number,
  ): void {
    if (abandonedView !== undefined) {
      this.options.preview.presentationStreamAbandoned(abandonedView);
    }
    const generation = ++this.connectionGeneration;
    const view = this.currentView;
    let streamMutationGeneration = notebookMutationGeneration;
    const previous = this.events;
    this.pendingEvents?.close();
    if (notebookMutationGeneration === undefined) {
      this.options.preview.presentationBuildStarted(view);
    } else {
      this.options.preview.presentationBuildStarted(view, notebookMutationGeneration);
    }
    const events = new EventSource(workspaceEventsUrl(this.options.eventsUrl, view));
    this.pendingEvents = previous === undefined ? undefined : events;
    if (previous === undefined) {
      this.events = events;
    }
    const pending = (operation: () => void) => {
      if (
        this.disposed ||
        generation !== this.connectionGeneration ||
        (this.events !== events && this.pendingEvents !== events)
      ) {
        return;
      }
      operation();
    };
    const current = (operation: () => void) => {
      if (this.disposed || this.events !== events || generation !== this.connectionGeneration) {
        return;
      }
      operation();
    };
    events.addEventListener("ready", (event) =>
      pending(() => {
        if (this.pendingEvents === events) {
          this.pendingEvents = undefined;
          this.events = events;
          previous?.close();
        }
        this.refreshInventory();
        this.options.source.reconcile();
        const baseline = parsePresentationBaseline(this.data(event));
        this.options.preview.presentationBaseline(
          view,
          baseline?.view === view ? baseline.revision : null,
        );
        connectionReady?.();
      }),
    );
    events.addEventListener("change", (event) =>
      current(() => {
        if (this.workspaceChanged(view, this.data(event), streamMutationGeneration)) {
          streamMutationGeneration = undefined;
        }
      }),
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
          this.observe(request);
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

  private workspaceChanged(
    view: string,
    data: string,
    notebookMutationGeneration?: number,
  ): boolean {
    const kind = parseWorkspaceChange(data);
    if (kind === undefined) {
      return false;
    }
    if (kind === "views") {
      this.refreshInventory();
      return false;
    }
    if (kind === "project") {
      this.options.source.externalChanges(parseSourceChanges(data));
      return false;
    }
    this.options.source.reconcile();
    if (kind === "build") {
      const build = parsePresentationBuild(data);
      if (build?.phase === "building") {
        if (notebookMutationGeneration === undefined) {
          this.options.preview.presentationBuildStarted(view);
        } else {
          this.options.preview.presentationBuildStarted(view, notebookMutationGeneration);
        }
      } else if (build?.phase === "complete") {
        if (notebookMutationGeneration === undefined) {
          this.options.preview.presentationBuildCompleted(view, build.revision);
        } else {
          this.options.preview.presentationBuildCompleted(
            view,
            build.revision,
            notebookMutationGeneration,
          );
        }
        if (notebookMutationGeneration === this.notebookMutationGeneration) {
          this.notebookMutationGeneration = undefined;
        }
        return notebookMutationGeneration !== undefined;
      }
      return false;
    }
    if (kind === "presentation") {
      const change = parsePresentationChange(data);
      if (change?.view === view) {
        this.options.preview.presentationChanged(view, change.revision);
      }
    }
    return false;
  }

  private requestActivation(request: ActiveViewRequest, reloadActive: boolean): void {
    if (
      request.generation <= this.acknowledgedActivation ||
      request.generation < this.latestActivation ||
      this.activationInFlight.has(request.generation)
    ) {
      return;
    }
    if (request.generation > this.latestActivation) {
      this.latestActivation = request.generation;
      this.activationAbort?.abort();
      this.options.views.cancelPendingSelection();
    }
    const owner = new AbortController();
    const timeout = setTimeout(
      () => owner.abort(new DOMException("View transition timed out", "TimeoutError")),
      ACTIVATION_TRANSITION_TIMEOUT_MS,
    );
    this.activationAbort = owner;
    this.activationInFlight.add(request.generation);
    void this.runActivation(request, reloadActive, owner, timeout);
  }

  private async runActivation(
    request: ActiveViewRequest,
    reloadActive: boolean,
    owner: AbortController,
    timeout: ReturnType<typeof setTimeout>,
  ): Promise<void> {
    let acknowledged = false;
    const connectionGeneration = this.connectionGeneration;
    try {
      acknowledged = await this.activate(
        request.view,
        request.generation,
        reloadActive,
        owner.signal,
      );
    } finally {
      clearTimeout(timeout);
      this.activationInFlight.delete(request.generation);
      if (this.activationAbort === owner) {
        this.activationAbort = undefined;
      }
    }
    if (this.disposed || request.generation !== this.latestActivation) {
      return;
    }
    if (acknowledged) {
      this.acknowledgedActivation = Math.max(this.acknowledgedActivation, request.generation);
    } else if (this.connectionGeneration === connectionGeneration) {
      this.connect(this.currentView);
    }
  }

  private async activate(
    view: string,
    generation: number,
    reloadActive: boolean,
    signal: AbortSignal,
  ): Promise<boolean> {
    const previousView = this.options.views.getSnapshot().current;
    let selected = false;
    try {
      if (!(await abortable(this.options.views.ensureAvailable(view, signal), signal))) {
        return false;
      }
      if (!this.isCurrentActivation(generation, signal)) {
        return false;
      }
      const alreadyActive = this.options.views.getSnapshot().current === view;
      if (
        !(await abortable(
          this.options.views.choose(view, "develop", undefined, signal, "agent"),
          signal,
        ))
      ) {
        return false;
      }
      selected = true;
      if (
        !this.isCurrentActivation(generation, signal) ||
        this.options.views.getSnapshot().current !== view
      ) {
        return false;
      }
      if (alreadyActive && reloadActive) {
        this.options.preview.reload();
      }
      if (!this.isCurrentActivation(generation, signal)) {
        return false;
      }
      await this.options.acknowledge(generation, view, signal);
      return this.isCurrentActivation(generation, signal);
    } catch (error) {
      if (
        selected &&
        error instanceof ViewActivationAcknowledgementError &&
        error.outcome === "rejected" &&
        !this.disposed &&
        generation === this.latestActivation &&
        this.options.views.getSnapshot().current === view
      ) {
        await this.rollbackActivation(previousView, "agent");
      }
      if (!this.disposed && !signal.aborted) {
        console.warn("Studio view could not be activated", error);
      }
      return false;
    }
  }

  private async rollbackActivation(
    previousView: string,
    selectionOwner: ViewSelectionOwner,
  ): Promise<void> {
    const owner = new AbortController();
    const timeout = setTimeout(
      () => owner.abort(new DOMException("View rollback timed out", "TimeoutError")),
      10_000,
    );
    try {
      await abortable(
        this.options.views.choose(
          previousView,
          "preserve",
          undefined,
          owner.signal,
          selectionOwner,
        ),
        owner.signal,
      );
    } catch (error) {
      if (!this.disposed) {
        console.warn("Studio view could not be restored after activation failed", error);
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  private isCurrentActivation(generation: number, signal: AbortSignal): boolean {
    return !this.disposed && !signal.aborted && generation === this.latestActivation;
  }

  private observe(request: ObserveViewRequest): void {
    if (
      request.activeViewGeneration !== undefined &&
      !this.disposed &&
      this.options.views.getSnapshot().current === request.view
    ) {
      this.options.preview.requestObservation(request);
    }
  }

  private data(event: Event): string {
    return event instanceof MessageEvent ? String(event.data) : "";
  }
}

const abortable = async <T>(operation: Promise<T>, signal: AbortSignal): Promise<T> => {
  signal.throwIfAborted();
  let abort = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    abort = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
