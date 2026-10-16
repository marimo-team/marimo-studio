import type { JsonValue } from "@marimo-studio/protocol/json";
import type { BrowserDiagnostic } from "@marimo-studio/protocol/runtime-status";

import {
  parseActiveViewRequest,
  parseEditorSessionBinding,
  parsePresentationBuild,
  parsePresentationChange,
  parseWorkspaceChange,
  presentationBuildNotice,
  type EditorSessionBinding,
  type ActiveViewRequest,
  type PreviewAutomationTarget,
} from "@marimo-studio/protocol/development-events";
import {
  EVENT_SOCKET_RETIRED,
  eventSocketUrl,
  parseStudioEvent,
} from "@marimo-studio/protocol/event-socket";
import { WORKSPACE_STREAM_QUERY_PARAM } from "@marimo-studio/protocol/query";
import {
  parsePresentationBaseline,
  parseSourceChanges,
  type SourceFileChange,
} from "@marimo-studio/protocol/source-events";

import type { ViewLanding, ViewSelectionOwner } from "../features/views/transition.ts";

import { RetrySchedule } from "../features/preview/retry-schedule.ts";
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
  editorSessionChanged(binding: EditorSessionBinding): void;
  reload(): void;
  automationTarget(view: string, reload: boolean, signal: AbortSignal): PreviewAutomationTarget;
  presentationBaseline(view: string, revision: string | null): void;
  presentationBuildStarted(view: string): void;
  presentationBuildCompleted(
    view: string,
    revision: string | null,
    notebookMutationGeneration?: number,
    diagnostic?: BrowserDiagnostic,
  ): void;
  presentationStreamAbandoned(view: string): void;
  presentationChanged(view: string, revision: string): void;
  serverRestarted(): void;
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

// The server closes a socket opened from a URL issued by an earlier server
// process with EVENT_SOCKET_RETIRED. Every other close, including a proxy
// error or an expired sign-in, leaves the stream worth reconnecting.
export const watchWorkspaceStreamClosure = (
  stream: WebSocket,
  closed: (retired: boolean) => void,
): void => {
  stream.addEventListener("close", (event) => closed(event.code === EVENT_SOCKET_RETIRED));
};

export const openWorkspaceEvents = (url: string): WebSocket => new WebSocket(eventSocketUrl(url));

const SOCKET_CONNECTING = 0;

// Closing a socket before its handshake completes logs a browser error, so a
// connecting socket closes once it opens. Its owner ignores later events.
export const closeWorkspaceEvents = (socket: WebSocket | undefined): void => {
  if (socket?.readyState === SOCKET_CONNECTING) {
    socket.addEventListener("open", () => socket.close(), { once: true });
    return;
  }
  socket?.close();
};

export class WorkspaceEventCoordinator {
  private events: WebSocket | undefined;
  private pendingEvents: WebSocket | undefined;
  private stopViews: (() => void) | undefined;
  private connectionGeneration = 0;
  private currentView: string;
  private acknowledgedActivation = -1;
  private latestActivation = -1;
  private activationAbort: AbortController | undefined;
  private readonly activationInFlight = new Set<number>();
  private notebookMutationGeneration: number | undefined;
  private readonly reconnects = new RetrySchedule();
  // The server replays a pending activation on each new stream. A decline such
  // as an unresolved Source conflict repeats, so replays back off.
  private readonly activationReplays = new RetrySchedule([0, 1_000, 2_000, 5_000, 10_000, 30_000]);
  private reconnect: ReturnType<typeof setTimeout> | undefined;
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
    clearTimeout(this.reconnect);
    this.activationAbort?.abort();
    this.activationAbort = undefined;
    this.stopViews?.();
    this.stopViews = undefined;
    this.connectionGeneration += 1;
    closeWorkspaceEvents(this.pendingEvents);
    this.pendingEvents = undefined;
    closeWorkspaceEvents(this.events);
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
    closeWorkspaceEvents(this.pendingEvents);
    this.pendingEvents = undefined;
    closeWorkspaceEvents(this.events);
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
    clearTimeout(this.reconnect);
    const view = this.currentView;
    let streamMutationGeneration = notebookMutationGeneration;
    const previous = this.events;
    closeWorkspaceEvents(this.pendingEvents);
    this.options.preview.presentationBuildStarted(view);
    const events = openWorkspaceEvents(workspaceEventsUrl(this.options.eventsUrl, view));
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
    const ready = (data: JsonValue) =>
      pending(() => {
        if (this.pendingEvents === events) {
          this.pendingEvents = undefined;
          this.events = events;
          closeWorkspaceEvents(previous);
        }
        this.reconnects.reset();
        this.refreshInventory();
        this.options.source.reconcile();
        const baseline = parsePresentationBaseline(data);
        this.options.preview.presentationBaseline(
          view,
          baseline?.view === view ? baseline.revision : null,
        );
        connectionReady?.();
      });
    watchWorkspaceStreamClosure(events, (retired) =>
      pending(() => {
        if (retired) {
          this.options.preview.serverRestarted();
          return;
        }
        this.reconnect = setTimeout(
          () => this.connect(undefined, connectionReady, this.notebookMutationGeneration),
          this.reconnects.next(),
        );
      }),
    );
    events.addEventListener("message", (message) => {
      const frame = parseStudioEvent(message.data);
      if (frame?.event === "ready") {
        ready(frame.data);
      } else if (frame?.event === "change") {
        current(() => {
          if (this.workspaceChanged(view, frame.data, streamMutationGeneration)) {
            streamMutationGeneration = undefined;
          }
        });
      } else if (frame?.event === "activate") {
        current(() => {
          const payload = parseActiveViewRequest(frame.data);
          if (payload) {
            this.requestActivation(payload, true);
          }
        });
      } else if (frame?.event === "session") {
        current(() => {
          const binding = parseEditorSessionBinding(frame.data);
          if (binding) {
            this.options.preview.editorSessionChanged(binding);
          }
        });
      }
    });
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
    data: JsonValue,
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
        this.options.preview.presentationBuildStarted(view);
      } else if (build?.phase === "complete") {
        const notice = presentationBuildNotice(build, view);
        if (notice) {
          this.options.preview.presentationBuildCompleted(
            view,
            build.revision,
            notebookMutationGeneration,
            notice,
          );
        } else if (notebookMutationGeneration === undefined) {
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
      this.activationReplays.reset();
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
      acknowledged = await this.activate(request, reloadActive, owner.signal);
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
      this.activationReplays.reset();
    } else if (this.connectionGeneration === connectionGeneration) {
      clearTimeout(this.reconnect);
      this.reconnect = setTimeout(() => {
        if (
          !this.disposed &&
          this.connectionGeneration === connectionGeneration &&
          request.generation === this.latestActivation
        ) {
          this.connect(this.currentView);
        }
      }, this.activationReplays.next());
    }
  }

  private async activate(
    request: ActiveViewRequest,
    reloadActive: boolean,
    signal: AbortSignal,
  ): Promise<boolean> {
    const { generation, view } = request;
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
      const preview = this.options.preview.automationTarget(
        view,
        alreadyActive && reloadActive,
        signal,
      );
      if (!this.isCurrentActivation(generation, signal)) {
        return false;
      }
      await this.options.acknowledge(request, preview, signal);
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
