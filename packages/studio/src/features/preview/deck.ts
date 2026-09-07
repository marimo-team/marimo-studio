import type {
  BrowserDiagnostic,
  RuntimeStatusReport,
} from "@marimo-studio/protocol/browser-observations";
import type {
  EditorSessionBinding,
  ObserveViewRequest,
} from "@marimo-studio/protocol/development-events";
import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import type { ControlFrameConnector } from "./control-sync.ts";
import type {
  PreviewNavigationOwner,
  StagedNavigationQuery,
  StagedPreviewView,
} from "./navigation.ts";
import type { NotebookMutationCompletion } from "./notebook-mutation-coordinator.ts";
import type { RecordBrowserObservation } from "./observation-remote.ts";
import type { EditorQuerySyncResult } from "./query-remote.ts";

import {
  nextPreviewDocumentLifecycleId,
  PreviewController,
  type PreviewFrameState,
} from "./controller.ts";
import { PreviewFrames, type CachedPreview } from "./frames.ts";
import { PreviewNavigation } from "./navigation.ts";
import { NotebookMutationCoordinator } from "./notebook-mutation-coordinator.ts";
import { observeFrameQuery } from "./query-sync.ts";
import { cloneRuntimeStatusReport, RuntimeDiagnostics } from "./runtime-diagnostics.ts";
import { previewStatus } from "./status.ts";

interface PreviewDeckOptions {
  initialView: string;
  initialRuntime: string;
  initialNavigation: ViewNavigationIntent;
  runtimes: readonly string[];
  viewUrl: (view: string, runtime: string, navigation?: ViewNavigationIntent) => string;
  supportUrl: (view: string) => string;
  syncQuery: (query: string) => void;
  syncEditorQuery: (
    query: string,
    operationId: string,
    writeGeneration: number,
    signal: AbortSignal,
  ) => Promise<EditorQuerySyncResult>;
  navigate: (view: string, intent: ViewNavigationIntent) => Promise<boolean>;
  recordObservation?: RecordBrowserObservation;
  connectControlFrame?: ControlFrameConnector;
}

export interface PreviewFrameDescriptor {
  active: boolean;
  id: string;
  interactive: boolean;
  primary: boolean;
  runtime: string;
  view?: string;
}

export interface PreviewDeckSnapshot {
  frames: readonly PreviewFrameDescriptor[];
  runtime: string;
  states: Readonly<Record<string, PreviewFrameState>>;
}

type Listener = () => void;

export class PreviewDeck {
  private readonly frames: PreviewFrames;
  private readonly listeners = new Set<Listener>();
  private readonly states = new Map<string, PreviewFrameState>();
  readonly frameIds: readonly string[];
  private runtime: string;
  private view: string;
  private navigation: ViewNavigationIntent;
  private editor: HTMLIFrameElement | undefined;
  private snapshot!: PreviewDeckSnapshot;
  private stopEditorQuerySync: (() => void) | undefined;
  private editorBindingGeneration = 0;
  private editorSessionId: string | undefined;
  private readonly notebookMutations: NotebookMutationCoordinator;
  private readonly presentationRevisions = new Map<string, string | null>();
  private readonly presentationBuilds = new Set<string>();
  private readonly navigationTransaction = new PreviewNavigation();
  private viewSwitch: {
    readonly view: string;
    readonly runtime: string;
    readonly ready?: Promise<boolean>;
  };

  constructor(private readonly options: PreviewDeckOptions) {
    this.runtime = options.initialRuntime;
    this.view = options.initialView;
    this.navigation = options.initialNavigation;
    this.frames = new PreviewFrames(options.runtimes, options.viewUrl, (view) => {
      if (view !== this.view) {
        this.presentationBuilds.delete(view);
        this.presentationRevisions.delete(view);
      }
    });
    this.notebookMutations = new NotebookMutationCoordinator({
      gate: (generation) => this.gateNotebookMutation(generation),
      markCachedViewsStale: () => this.markCachedViewsStale(),
      resetActive: () => this.activeController()?.reload(),
      saveFailed: () =>
        this.notebookMutationFailed({
          code: "notebook-save-failed",
          message: "Notebook save failed.",
          hint: "Retry the save to update this view.",
        }),
      transactionFailed: () =>
        this.notebookMutationFailed({
          code: "notebook-sync-failed",
          message: "Notebook change could not be synchronized.",
          hint: "Retry the edit to update this view.",
        }),
    });
    this.viewSwitch = { view: this.view, runtime: this.runtime };
    for (const runtime of options.runtimes) {
      const initial = this.frames.select(runtime, this.view, this.navigation);
      this.states.set(runtime, initial.state!);
    }
    this.frameIds = this.frames.ids;
    this.updateSnapshot();
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): PreviewDeckSnapshot => this.snapshot;

  private readonly recordObservation: RecordBrowserObservation = async (observation) => {
    if (!this.options.recordObservation) {
      return;
    }
    const sessionId =
      observation.runtime === DEFAULT_RUNTIME_ID
        ? (this.editorSessionId ?? null)
        : observation.sessionId;
    await this.options.recordObservation({
      ...observation,
      sessionId,
      runtimeStatus: {
        ...observation.runtimeStatus,
        sessionId,
        transitions: observation.runtimeStatus.transitions.map((transition) => ({
          ...transition,
          sessionId,
        })),
      },
    });
  };

  attach(editor: HTMLIFrameElement, frames: ReadonlyMap<string, HTMLIFrameElement>): void {
    if (this.editor) {
      return;
    }
    this.editor = editor;
    this.frames.attach(frames);
    this.ensure(this.runtime, this.view);
    this.bindEditor();
  }

  switchRuntime(runtime: string): void {
    if (
      runtime === this.runtime ||
      this.navigationTransaction.pending ||
      !this.options.runtimes.includes(runtime)
    ) {
      return;
    }
    this.deactivateActive();
    this.runtime = runtime;
    const slot = this.frames.select(runtime, this.view, this.navigation);
    this.states.set(runtime, slot.state!);
    const controller = this.ensure(runtime, this.view);
    const reload = slot.stale;
    slot.stale = false;
    if (this.presentationBuilds.has(this.view)) {
      controller?.presentationBuildStarted();
    }
    if (this.presentationRevisions.has(this.view)) {
      controller?.presentationBaseline(this.presentationRevisions.get(this.view)!);
    }
    const ready = controller?.activate(this.navigation, undefined, reload);
    this.viewSwitch = { view: this.view, runtime, ready };
    this.publish();
    controller?.requestResize();
  }

  stageView(
    view: string,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
  ): StagedPreviewView {
    const previousView = this.view;
    const previousNavigation = this.navigation;
    const ready = this.applyView(view, navigation, signal);
    const owner = this.viewSwitch;
    let rollback: Promise<void> | undefined;
    return {
      ready,
      rollback: () => {
        rollback ??= (async () => {
          if (this.viewSwitch !== owner) {
            return;
          }
          await this.applyView(previousView, previousNavigation);
        })();
        return rollback;
      },
    };
  }

  stageNavigation(
    view: string,
    changed: boolean,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
  ): StagedPreviewView {
    return this.navigationTransaction.stage(
      navigation ? (owner) => this.stageNavigationQuery(navigation.query, owner) : undefined,
      changed ? () => this.stageView(view, navigation, signal) : undefined,
    );
  }

  private applyView(
    view: string,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
  ): Promise<boolean> {
    this.deactivateActive();
    this.view = view;
    this.navigation = navigation ?? { query: this.navigation.query, hash: "" };
    for (const runtime of this.options.runtimes) {
      const slot = this.frames.select(runtime, view, this.navigation);
      this.states.set(runtime, slot.state!);
    }
    const active = this.frames.find(this.runtime, view)!;
    const controller = this.ensure(this.runtime, view);
    const reload = active.stale;
    active.stale = false;
    const ready = controller?.activate(this.navigation, signal, reload) ?? Promise.resolve(false);
    this.viewSwitch = { view, runtime: this.runtime, ready };
    this.publish();
    return ready;
  }

  prepareViewDeletion(view: string): Promise<boolean> {
    if (view !== this.view || this.viewSwitch.view !== view) {
      return Promise.resolve(false);
    }
    for (const slot of this.frames.slots) {
      if (slot.runtime !== this.runtime || slot.view !== this.view) {
        this.frames.release(slot);
      }
    }
    for (const runtime of this.options.runtimes) {
      const selected = this.frames.select(runtime, this.view, this.navigation);
      this.states.set(runtime, selected.state!);
    }
    this.publish();
    return this.viewSwitch.runtime === this.runtime
      ? (this.viewSwitch.ready ?? Promise.resolve(true))
      : Promise.resolve(true);
  }

  releaseView(view: string): void {
    this.presentationBuilds.delete(view);
    this.presentationRevisions.delete(view);
    let released = false;
    for (const slot of this.frames.slots) {
      if (slot.view === view && !this.isActive(slot)) {
        this.frames.release(slot);
        released = true;
      }
    }
    if (released) {
      this.publish();
    }
  }

  replaceView(view: string): void {
    this.presentationBuilds.delete(view);
    this.presentationRevisions.delete(view);
    let changed = false;
    for (const slot of this.frames.slots) {
      if (slot.view !== view) {
        continue;
      }
      if (this.isActive(slot)) {
        slot.stale = false;
        slot.controller?.reload();
      } else {
        this.frames.release(slot);
      }
      changed = true;
    }
    if (changed) {
      this.publish();
    }
  }

  navigateWithinView(navigation: ViewNavigationIntent): void {
    this.navigation = navigation;
    for (const runtime of this.options.runtimes) {
      const slot = this.frames.select(runtime, this.view, navigation);
      if (runtime === this.runtime) {
        slot.controller?.navigateWithinView(navigation);
      }
      this.states.set(runtime, slot.state!);
    }
    this.publish();
  }

  synchronizeNavigationQuery(query: string): Promise<boolean> {
    return (
      this.ensure(this.runtime, this.view)?.synchronizeNavigationQuery(query) ??
      Promise.resolve(false)
    );
  }

  cancelNavigation(): void {
    this.frames.find(this.runtime, this.view)?.controller?.cancelNavigation();
  }

  requestResize(): void {
    this.editor?.contentWindow?.dispatchEvent(new Event("resize"));
    this.frames.slots.forEach(({ controller }) => controller?.requestResize());
  }

  requestObservation(request: ObserveViewRequest): void {
    const slot = this.frames.find(request.runtime, request.view);
    if (
      !slot ||
      request.view !== this.view ||
      request.runtime !== this.runtime ||
      !this.isActive(slot)
    ) {
      return;
    }
    const controller = this.ensure(request.runtime, request.view);
    if (!controller) {
      return;
    }
    if (slot.stale) {
      slot.stale = false;
      void controller
        .activate(this.navigation, undefined, true)
        .then((ready) => ready && controller.requestObservation(request));
      return;
    }
    controller.requestObservation(request);
  }

  reload(): void {
    const active = this.frames.find(this.runtime, this.view);
    const controller = this.ensure(this.runtime, this.view);
    if (active) {
      active.stale = false;
    }
    controller?.reload();
  }

  editorSessionChanged(binding: EditorSessionBinding): void {
    if (binding.generation <= this.editorBindingGeneration) {
      return;
    }
    const previousSessionId = this.editorSessionId;
    const hadEarlierBinding = this.editorBindingGeneration > 0 || binding.replaced;
    this.editorBindingGeneration = binding.generation;
    this.editorSessionId = binding.sessionId;
    if (hadEarlierBinding && previousSessionId === binding.sessionId) {
      return;
    }
    const reload = hadEarlierBinding;
    const active = this.frames.find(this.runtime, this.view);
    for (const slot of this.frames.slots) {
      if (!slot.controller) {
        continue;
      }
      slot.controller.editorSessionChanged(binding.sessionId, reload && slot === active);
      if (reload && slot !== active) {
        slot.stale = true;
      }
    }
  }

  editorDocumentReloaded(): boolean {
    return this.notebookMutations.editorReloaded();
  }

  notebookMutationPending(generation: number, acknowledgement: MessagePort): void {
    this.notebookMutations.admit(generation, acknowledgement);
  }

  notebookMutationSaved(generation: number): boolean {
    return this.notebookMutations.saved(generation);
  }

  notebookMutationSaveFailed(generation: number): void {
    this.notebookMutations.saveFailed(generation);
  }

  notebookMutationTransactionFailed(generation: number): void {
    this.notebookMutations.transactionFailed(generation);
  }

  notebookMutationTransactionApplied(generation: number, changed: boolean): void {
    this.notebookMutations.transactionApplied(generation, changed);
  }

  presentationBuildStarted(view: string, _notebookMutationGeneration?: number): void {
    this.presentationBuilds.add(view);
    const active = this.frames.find(this.runtime, view);
    if (view === this.view && !active?.controller) {
      const selected = active ?? this.frames.select(this.runtime, view, this.navigation);
      this.states.set(this.runtime, selected.state!);
      this.ensure(this.runtime, view);
    }
    for (const slot of this.frames.slots) {
      if (slot.view === view) {
        slot.controller?.presentationBuildStarted();
      }
    }
  }

  presentationBuildCompleted(
    view: string,
    revision: string | null,
    notebookMutationGeneration?: number,
  ): void {
    const active = view === this.view ? this.frames.find(this.runtime, view) : undefined;
    const activeController = active?.controller;
    this.notebookMutations.buildCompleted(notebookMutationGeneration, () => {
      let interactivityChanged = false;
      this.presentationBuilds.delete(view);
      if (revision !== null) {
        this.presentationRevisions.set(view, revision);
      }
      for (const slot of this.frames.slots) {
        if (slot.view === view) {
          if (
            revision !== null &&
            slot === active &&
            slot.controller === activeController &&
            slot.stale &&
            this.isActive(slot)
          ) {
            slot.stale = false;
            interactivityChanged = true;
          }
          slot.controller?.presentationBuildCompleted(revision);
        }
      }
      if (interactivityChanged) {
        this.publish();
      }
    });
  }

  presentationStreamAbandoned(view: string): void {
    const incompleteBuild = this.presentationBuilds.delete(view);
    for (const slot of this.frames.slots) {
      if (slot.view === view) {
        slot.controller?.presentationStreamAbandoned(incompleteBuild);
      }
    }
  }

  presentationChanged(view: string, revision: string): void {
    if (this.presentationRevisions.get(view) === revision) {
      return;
    }
    this.presentationRevisions.set(view, revision);
    for (const slot of this.frames.slots) {
      if (slot.view === view) {
        slot.controller?.presentationChanged(revision);
      }
    }
  }

  presentationBaseline(view: string, revision: string | null): void {
    this.presentationRevisions.set(view, revision);
    for (const slot of this.frames.slots) {
      if (slot.view === view) {
        slot.controller?.presentationBaseline(revision);
      }
    }
  }

  runtimeDiagnostics(runtime = this.runtime): RuntimeStatusReport | undefined {
    const slot = this.frames.find(runtime, this.view);
    const report = slot?.controller?.runtimeStatus() ?? slot?.state?.runtimeStatus;
    return report === undefined ? undefined : cloneRuntimeStatusReport(report);
  }

  dispose(): void {
    this.stopEditorQuerySync?.();
    this.frames.dispose();
    this.listeners.clear();
  }

  private bindEditor(): void {
    const editor = this.editor;
    if (!editor) {
      return;
    }
    this.stopEditorQuerySync = observeFrameQuery(editor, (query, operationId, completed) => {
      if (operationId === undefined) {
        this.receiveNavigationQuery(query);
      }
      this.frames
        .find(this.runtime, this.view)
        ?.controller?.editorQueryChanged(query, operationId, completed);
    });
  }

  private ensure(runtime: string, view: string): PreviewController | undefined {
    const slot = this.frames.find(runtime, view);
    if (!slot || !this.editor || !slot.frame) {
      return undefined;
    }
    if (slot.controller) {
      return slot.controller;
    }
    const controller = new PreviewController(
      view,
      runtime,
      this.editor,
      slot.frame,
      this.options.viewUrl,
      this.options.supportUrl,
      this.options.syncQuery,
      this.options.syncEditorQuery,
      (next, intent) =>
        this.isActive(slot) ? this.options.navigate(next, intent) : Promise.resolve(false),
      (state) => this.receive(slot, state),
      this.recordObservation,
      this.options.connectControlFrame,
      slot.navigation!,
      (query) => {
        if (this.isActive(slot)) {
          this.receiveNavigationQuery(query);
        }
      },
      slot.state!.lifecycleId,
      () => nextPreviewDocumentLifecycleId(),
      this.editorSessionId,
    );
    slot.controller = controller;
    if (this.presentationBuilds.has(view)) {
      controller.presentationBuildStarted();
    }
    if (this.presentationRevisions.has(view) && this.isActive(slot)) {
      controller.presentationBaseline(this.presentationRevisions.get(view)!);
    }
    return controller;
  }

  private stageNavigationQuery(
    query: string,
    transaction: PreviewNavigationOwner,
  ): StagedNavigationQuery {
    const runtime = this.runtime;
    const view = this.view;
    const previousQuery = this.navigation.query;
    let accepted = false;
    let rollback: Promise<boolean> | undefined;
    return {
      ready: this.synchronizeNavigationQuery(query).then((result) => {
        accepted = result;
        return result;
      }),
      rollback: () => {
        if (!rollback) {
          const currentOwner =
            this.navigationTransaction.owns(transaction) &&
            this.runtime === runtime &&
            this.view === view
              ? this.frames.find(runtime, view)?.controller
              : undefined;
          if (accepted && currentOwner) {
            rollback = currentOwner.rollbackNavigation(previousQuery);
          } else {
            currentOwner?.cancelNavigation();
            rollback = Promise.resolve(!accepted || currentOwner !== undefined);
          }
        }
        return rollback;
      },
    };
  }

  private isActive(slot: CachedPreview): boolean {
    return slot.runtime === this.runtime && slot.view === this.view;
  }

  private activeController(): PreviewController | undefined {
    return this.frames.find(this.runtime, this.view)?.controller;
  }

  private async gateNotebookMutation(generation: number): Promise<NotebookMutationCompletion> {
    for (const slot of this.frames.slots) {
      if (slot.controller && !this.isActive(slot)) {
        this.invalidateNotebookSlot(slot);
      }
    }
    while (true) {
      const slot = this.frames.find(this.runtime, this.view);
      const controller = slot?.controller;
      if (!slot || !controller) {
        return { owner: slot ?? {}, complete: () => {} };
      }
      try {
        const unchanged = await controller.notebookMutationPending(generation, true);
        if (slot.controller === controller && this.isActive(slot)) {
          return {
            owner: controller,
            complete: () => {
              if (slot.controller === controller && this.isActive(slot)) {
                if (unchanged()) {
                  slot.stale = false;
                  this.publish();
                }
              }
            },
          };
        }
      } catch {
        if (slot.controller === controller && this.isActive(slot)) {
          this.invalidateNotebookSlot(slot);
          const placeholder = this.installMutationPlaceholder();
          return {
            owner: placeholder,
            complete: () => {
              if (!this.isActive(placeholder)) {
                return;
              }
              placeholder.controller ??= this.ensure(this.runtime, this.view);
            },
          };
        }
      }
    }
  }

  private installMutationPlaceholder(): CachedPreview {
    const slot = this.frames.select(this.runtime, this.view, this.navigation);
    const runtimeStatus = new RuntimeDiagnostics({ runtime: this.runtime, view: this.view }).record(
      {
        phase: "synchronizing",
        diagnostics: [],
      },
    );
    slot.state = {
      ...slot.state!,
      runtimeStatus,
      status: previewStatus(this.runtime, runtimeStatus.current),
    };
    this.states.set(this.runtime, slot.state);
    this.publish();
    return slot;
  }

  private notebookMutationFailed(failure: { code: string; hint: string; message: string }): void {
    const controller = this.activeController();
    if (controller) {
      if (failure.code === "notebook-save-failed") {
        controller.notebookMutationSaveFailed(true);
      } else {
        controller.notebookMutationTransactionFailed(true);
      }
      return;
    }
    const slot = this.frames.find(this.runtime, this.view);
    if (!slot?.state) {
      return;
    }
    const diagnostic: BrowserDiagnostic = {
      ...failure,
      severity: "error",
      scope: "runtime",
      view: this.view,
    };
    const runtimeStatus = new RuntimeDiagnostics({ runtime: this.runtime, view: this.view }).record(
      {
        phase: "failed",
        diagnostics: [diagnostic],
      },
    );
    slot.state = {
      ...slot.state,
      runtimeStatus,
      status: previewStatus(this.runtime, runtimeStatus.current),
    };
    this.states.set(this.runtime, slot.state);
    this.publish();
  }

  private markCachedViewsStale(): void {
    for (const slot of this.frames.slots) {
      if (!slot.controller) {
        continue;
      }
      if (this.isActive(slot)) {
        slot.stale = true;
        slot.controller.presentationBaseline(null);
        if (slot.view !== undefined) {
          this.presentationBuilds.delete(slot.view);
          this.presentationRevisions.delete(slot.view);
        }
      } else {
        this.invalidateNotebookSlot(slot);
      }
    }
    this.publish();
  }

  private invalidateNotebookSlot(slot: CachedPreview): void {
    const view = slot.view;
    this.frames.release(slot);
    if (view !== undefined) {
      this.presentationBuilds.delete(view);
      this.presentationRevisions.delete(view);
    }
  }

  private deactivateActive(): void {
    const active = this.frames.find(this.runtime, this.view);
    if (active && this.notebookMutations.pending) {
      this.invalidateNotebookSlot(active);
      return;
    }
    active?.controller?.deactivate();
  }

  private receive(slot: CachedPreview, state: PreviewFrameState): void {
    if (slot.view === undefined) {
      return;
    }
    slot.state = state;
    if (slot.view !== this.view) {
      return;
    }
    this.states.set(slot.runtime, state);
    this.publish();
  }

  private receiveNavigationQuery(query: string): void {
    const next = publicNotebookQuery(query);
    if (next === this.navigation.query) {
      return;
    }
    this.navigation = { ...this.navigation, query: next };
    for (const runtime of this.options.runtimes) {
      const slot = this.frames.select(runtime, this.view, this.navigation);
      this.states.set(runtime, slot.state!);
    }
  }

  private publish(): void {
    this.updateSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private updateSnapshot(): void {
    this.snapshot = {
      runtime: this.runtime,
      states: Object.fromEntries(this.states),
      frames: this.frames.slots.map(({ controller, id, runtime, stale, view }) => {
        const active = runtime === this.runtime && view === this.view;
        return {
          id,
          runtime,
          view,
          active,
          interactive: active && !stale && (controller?.readyForInteraction() ?? false),
          primary: view === this.view,
        };
      }),
    };
  }
}
