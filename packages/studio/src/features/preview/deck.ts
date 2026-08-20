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
import type { NotebookMutationCompletion } from "./notebook-mutation-coordinator.ts";
import type { RecordBrowserObservation } from "./observation-remote.ts";
import type { EditorQuerySyncResult } from "./query-remote.ts";
import type { LoadedRuntimeAvailability, LoadRuntimeAvailability } from "./runtime-remote.ts";

import {
  nextPreviewDocumentLifecycleId,
  PreviewController,
  type PreviewFrameState,
} from "./controller.ts";
import { NotebookMutationCoordinator } from "./notebook-mutation-coordinator.ts";
import { observeFrameQuery } from "./query-sync.ts";
import { cloneRuntimeStatusReport, RuntimeDiagnostics } from "./runtime-diagnostics.ts";
import { initialPreviewRuntime } from "./runtime.ts";
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

export const PREVIEW_VIEW_CACHE_SIZE = 3;
export const WASM_PREVIEW_VIEW_CACHE_SIZE = 1;

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
  runtimes: readonly RuntimeDescriptor[];
  states: Readonly<Record<string, PreviewFrameState>>;
}

export interface StagedPreviewView {
  ready: Promise<boolean>;
  commit?(): void;
  rollback(): Promise<void>;
}

interface CachedPreview {
  readonly id: string;
  readonly runtime: string;
  controller?: PreviewController;
  frame?: HTMLIFrameElement;
  lastUsed: number;
  navigation?: ViewNavigationIntent;
  stale: boolean;
  state?: PreviewFrameState;
  view?: string;
}

interface StagedNavigationQuery {
  ready: Promise<boolean>;
  rollback(): Promise<boolean>;
}

interface PreviewNavigationTransaction {
  readonly id: number;
}

type Listener = () => void;
const RUNTIME_AVAILABILITY_TIMEOUT_MS = 2_000;

const startingFrameState = (
  runtime: string,
  view: string,
  url: string,
  lifecycleId: number,
): PreviewFrameState => {
  const runtimeStatus = new RuntimeDiagnostics({ runtime, view }).report();
  return {
    url,
    lifecycleId,
    runtimeStatus,
    status: previewStatus(runtime, runtimeStatus.current),
  };
};

const sameNavigation = (left: ViewNavigationIntent, right: ViewNavigationIntent): boolean =>
  left.query === right.query && left.hash === right.hash;

export class PreviewDeck {
  private readonly slots: CachedPreview[] = [];
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
  private navigationTransaction: PreviewNavigationTransaction | undefined;
  private navigationGeneration = 0;
  private lastUsed = 0;
  private viewSwitch: {
    readonly view: string;
    readonly runtime: string;
    readonly ready?: Promise<boolean>;
  };

  constructor(private readonly options: PreviewDeckOptions) {
    this.runtimes = new Map(options.runtimes.map((runtime) => [runtime.id, runtime]));
    this.controlPeer = options.runtimes.find((runtime) => runtime.controls === "peer")?.id;
    this.availableRuntimes = this.resolveRuntimes(options.availableRuntimes);
    this.sourceRevisions = { ...options.sourceRevisions };
    this.presentationRevision = options.presentationRevision;
    if (!this.availableRuntimes.some((runtime) => runtime.id === options.initialRuntime.id)) {
      throw new Error("The initial preview runtime is unavailable for the selected view");
    }
    this.runtime = options.initialRuntime.id;
    this.view = options.initialView;
    this.navigation = options.initialNavigation;
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
      const cacheSize =
        runtime === DEFAULT_RUNTIME_ID ? PREVIEW_VIEW_CACHE_SIZE : WASM_PREVIEW_VIEW_CACHE_SIZE;
      for (let index = 0; index < cacheSize; index += 1) {
        this.slots.push({
          id: index === 0 ? runtime : `${runtime}:${index}`,
          runtime,
          lastUsed: 0,
          stale: false,
        });
      }
      const initial = this.selectSlot(runtime, this.view, this.navigation);
      this.states.set(runtime, initial.state!);
    }
    this.frameIds = this.slots.map(({ id }) => id);
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
    if (this.disposed || this.editor) {
      return;
    }
    this.editor = editor;
    for (const slot of this.slots) {
      slot.frame = frames.get(slot.id);
    }
    this.ensure(this.runtime, this.view);
    this.bindEditor();
  }

  switchRuntime(runtime: string): void {
    if (
      runtime === this.runtime ||
      this.navigationTransaction !== undefined ||
      !this.options.runtimes.includes(runtime)
    ) {
      return;
    }
    this.deactivateActive();
    this.runtime = runtime;
    const slot = this.selectSlot(runtime, this.view, this.navigation);
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
    const transaction = { id: ++this.navigationGeneration };
    this.navigationTransaction = transaction;
    const query = navigation ? this.stageNavigationQuery(navigation.query, transaction) : undefined;
    let preview: StagedPreviewView | undefined;
    let rollingBack = false;
    let rollback: Promise<void> | undefined;
    const ready = (async () => {
      if (
        (query && !(await query.ready)) ||
        rollingBack ||
        this.navigationTransaction !== transaction
      ) {
        return false;
      }
      if (!changed) {
        return true;
      }
      preview = signal
        ? this.stageView(view, navigation, signal)
        : this.stageView(view, navigation);
      if (rollingBack) {
        await preview.rollback();
        return false;
      }
      const prepared = await preview.ready;
      return !rollingBack && this.navigationTransaction === transaction && prepared;
    })();
    return {
      ready,
      commit: () => {
        if (this.navigationTransaction === transaction) {
          this.navigationTransaction = undefined;
        }
      },
      rollback: () => {
        rollingBack = true;
        rollback ??= (async () => {
          if (this.navigationTransaction !== transaction) {
            return;
          }
          const failures: unknown[] = [];
          try {
            try {
              await preview?.rollback();
            } catch (error) {
              failures.push(error);
            }
            try {
              if (!((await query?.rollback()) ?? true)) {
                failures.push(new Error("The previous notebook query could not be restored."));
              }
            } catch (error) {
              failures.push(error);
            }
          } finally {
            if (this.navigationTransaction === transaction) {
              this.navigationTransaction = undefined;
            }
          }
          if (failures.length === 1) {
            throw failures[0];
          }
          if (failures.length > 1) {
            throw new AggregateError(failures, "The previous view could not be restored.");
          }
        })();
        return rollback;
      },
    };
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
      const slot = this.selectSlot(runtime, view, this.navigation);
      this.states.set(runtime, slot.state!);
    }
    const active = this.slotFor(this.runtime, view)!;
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
    for (const slot of this.slots) {
      if (slot.runtime !== this.runtime || slot.view !== this.view) {
        this.releaseSlot(slot);
      }
    }
    for (const runtime of this.options.runtimes) {
      const selected = this.selectSlot(runtime, this.view, this.navigation);
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
    for (const slot of this.slots) {
      if (slot.view === view && !this.isActive(slot)) {
        this.releaseSlot(slot);
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
    for (const slot of this.slots) {
      if (slot.view !== view) {
        continue;
      }
      if (this.isActive(slot)) {
        slot.stale = false;
        slot.controller?.reload();
      } else {
        this.releaseSlot(slot);
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
      const slot = this.selectSlot(runtime, this.view, navigation);
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
    this.slotFor(this.runtime, this.view)?.controller?.cancelNavigation();
  }

  requestResize(): void {
    this.editor?.contentWindow?.dispatchEvent(new Event("resize"));
    this.slots.forEach(({ controller }) => controller?.requestResize());
  }

  requestObservation(request: ObserveViewRequest): void {
    const slot = this.slotFor(request.runtime, request.view);
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
    const active = this.slotFor(this.runtime, this.view);
    const controller = this.ensure(this.runtime, this.view);
    if (active) {
      active.stale = false;
    }
    controller?.reload();
  }

  editorSessionChanged(binding: EditorSessionBinding): void {
    if (this.disposed || binding.generation <= this.editorBindingGeneration) {
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
    const active = this.slotFor(this.runtime, this.view);
    for (const slot of this.slots) {
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
    const active = this.slotFor(this.runtime, view);
    if (view === this.view && !active?.controller) {
      const selected = active ?? this.selectSlot(this.runtime, view, this.navigation);
      this.states.set(this.runtime, selected.state!);
      this.ensure(this.runtime, view);
    }
    for (const slot of this.slots) {
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
    const active = view === this.view ? this.slotFor(this.runtime, view) : undefined;
    const activeController = active?.controller;
    this.notebookMutations.buildCompleted(notebookMutationGeneration, () => {
      let interactivityChanged = false;
      this.presentationBuilds.delete(view);
      if (revision !== null) {
        this.presentationRevisions.set(view, revision);
      }
      for (const slot of this.slots) {
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
    for (const slot of this.slots) {
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
    for (const slot of this.slots) {
      if (slot.view === view) {
        slot.controller?.presentationChanged(revision);
      }
    }
  }

  presentationBaseline(view: string, revision: string | null): void {
    this.presentationRevisions.set(view, revision);
    for (const slot of this.slots) {
      if (slot.view === view) {
        slot.controller?.presentationBaseline(revision);
      }
    }
  }

  runtimeDiagnostics(runtime = this.runtime): RuntimeStatusReport | undefined {
    const slot = this.slotFor(runtime, this.view);
    const report = slot?.controller?.runtimeStatus() ?? slot?.state?.runtimeStatus;
    return report === undefined ? undefined : cloneRuntimeStatusReport(report);
  }

  dispose(): void {
    this.stopEditorQuerySync?.();
    this.slots.forEach((slot) => this.releaseSlot(slot));
    this.listeners.clear();
    this.editor = undefined;
    this.frames = undefined;
    if (failures.length === 1) {
      throw failures[0];
    }
    if (failures.length > 1) {
      throw new AggregateError(failures, "Preview deck disposal failed");
    }
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
      this.slotFor(this.runtime, this.view)?.controller?.editorQueryChanged(
        query,
        operationId,
        completed,
      );
    });
  }

  private ensure(runtime: string, view: string): PreviewController | undefined {
    const slot = this.slotFor(runtime, view);
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
    transaction: PreviewNavigationTransaction,
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
            this.navigationTransaction === transaction &&
            this.runtime === runtime &&
            this.view === view
              ? this.slotFor(runtime, view)?.controller
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

  private selectSlot(
    runtime: string,
    view: string,
    navigation: ViewNavigationIntent,
  ): CachedPreview {
    const existing = this.slotFor(runtime, view);
    if (existing) {
      this.touch(existing);
      if (!sameNavigation(existing.navigation!, navigation)) {
        existing.navigation = navigation;
        if (!existing.controller && existing.state) {
          existing.state = {
            ...existing.state,
            url: this.options.viewUrl(view, runtime, navigation),
          };
        }
      }
      return existing;
    }
    const candidates = this.slots.filter((slot) => slot.runtime === runtime);
    const selected =
      candidates.find(({ view: assigned }) => assigned === undefined) ??
      candidates.reduce((oldest, slot) => (slot.lastUsed < oldest.lastUsed ? slot : oldest));
    this.releaseSlot(selected);
    selected.view = view;
    selected.navigation = navigation;
    selected.state = startingFrameState(
      runtime,
      view,
      this.options.viewUrl(view, runtime, navigation),
      nextPreviewDocumentLifecycleId(),
    );
    this.touch(selected);
    return selected;
  }

  private slotFor(runtime: string, view: string): CachedPreview | undefined {
    return this.slots.find((slot) => slot.runtime === runtime && slot.view === view);
  }

  private touch(slot: CachedPreview): void {
    this.lastUsed += 1;
    slot.lastUsed = this.lastUsed;
  }

  private releaseSlot(slot: CachedPreview): void {
    const releasedView = slot.view;
    slot.controller?.deactivate();
    slot.controller?.dispose();
    slot.controller = undefined;
    slot.stale = false;
    slot.state = undefined;
    slot.navigation = undefined;
    slot.view = undefined;
    slot.lastUsed = 0;
    if (slot.frame) {
      delete slot.frame.dataset.sessionId;
      slot.frame.src = "about:blank";
    }
    if (releasedView !== undefined && releasedView !== this.view) {
      this.presentationBuilds.delete(releasedView);
      this.presentationRevisions.delete(releasedView);
    }
  }

  private isActive(slot: CachedPreview): boolean {
    return slot.runtime === this.runtime && slot.view === this.view;
  }

  private activeController(): PreviewController | undefined {
    return this.slotFor(this.runtime, this.view)?.controller;
  }

  private async gateNotebookMutation(generation: number): Promise<NotebookMutationCompletion> {
    for (const slot of this.slots) {
      if (slot.controller && !this.isActive(slot)) {
        this.invalidateNotebookSlot(slot);
      }
    }
    while (true) {
      const slot = this.slotFor(this.runtime, this.view);
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
    const slot = this.selectSlot(this.runtime, this.view, this.navigation);
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
    const slot = this.slotFor(this.runtime, this.view);
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
    for (const slot of this.slots) {
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
    this.releaseSlot(slot);
    if (view !== undefined) {
      this.presentationBuilds.delete(view);
      this.presentationRevisions.delete(view);
    }
  }

  private deactivateActive(): void {
    const active = this.slotFor(this.runtime, this.view);
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
      const slot = this.selectSlot(runtime, this.view, this.navigation);
      this.states.set(runtime, slot.state!);
    }
  }

  private publish(): void {
    if (this.disposed) {
      return;
    }
    this.updateSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private updateSnapshot(): void {
    this.snapshot = {
      runtime: this.runtime,
      runtimes: this.availableRuntimes,
      states: Object.fromEntries(this.states),
      frames: this.slots.map(({ controller, id, runtime, stale, view }) => {
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

  private resolveRuntimes(runtimeIds: readonly string[]): readonly RuntimeDescriptor[] {
    const runtimes = runtimeIds.map((runtime) => {
      const descriptor = this.runtimes.get(runtime);
      if (!descriptor) {
        throw new Error(`Preview runtime ${JSON.stringify(runtime)} is not in the runtime catalog`);
      }
      return descriptor;
    });
    if (runtimes.length === 0 || new Set(runtimeIds).size !== runtimes.length) {
      throw new Error("Preview runtime availability must contain unique runtime IDs");
    }
    return runtimes;
  }

  private setAvailableRuntimes(runtimeIds: readonly string[]): void {
    const available = this.resolveRuntimes(runtimeIds);
    const nextIds = new Set(available.map(({ id }) => id));
    const cleanupFailures: unknown[] = [];
    this.previews.forEach((controller, runtime) => {
      if (nextIds.has(runtime)) {
        return;
      }
      this.previews.delete(runtime);
      const frame = this.frames?.get(runtime);
      if (frame) {
        frame.src = "about:blank";
      }
      const descriptor = this.runtimes.get(runtime);
      if (descriptor) {
        this.states.set(
          runtime,
          startingFrameState(
            descriptor,
            this.view,
            this.options.viewUrl(this.view, descriptor.id, this.presentationRevision),
          ),
        );
      }
      try {
        controller.dispose();
      } catch (error) {
        cleanupFailures.push(error);
      }
    });
    this.availableRuntimes = available;
    if (!this.isAvailable(this.runtime)) {
      this.runtime = initialPreviewRuntime({
        available: this.availableRuntimes,
        configured: this.options.defaultRuntime,
      }).id;
      this.ensure(this.runtime);
    }
    if (cleanupFailures.length > 0) {
      console.warn(
        "Unavailable preview runtime cleanup failed",
        cleanupFailures.length === 1
          ? cleanupFailures[0]
          : new AggregateError(cleanupFailures, "Preview runtime retirement failed"),
      );
    }
  }

  private isAvailable(runtime: string): boolean {
    return this.availableRuntimes.some((candidate) => candidate.id === runtime);
  }

  private repairRuntimeIds(): readonly string[] {
    const runtimes = this.options.runtimes
      .filter(({ execution }) => execution !== "prepared")
      .map(({ id }) => id);
    return runtimes.length > 0 ? runtimes : [this.options.runtimes[0]!.id];
  }

  private forwardSourceChange(kind: ShellChangeKind): void {
    this.previews.forEach((controller, runtime) => {
      if (this.isAvailable(runtime)) {
        controller.sourceChanged(kind);
      }
    });
  }

  private cancelAvailabilityRefresh(): void {
    this.availabilityGeneration += 1;
    this.availabilityController?.abort(
      new DOMException("Runtime availability was superseded", "AbortError"),
    );
    this.availabilityController = undefined;
    if (this.availabilityRetryTimer !== undefined) {
      clearTimeout(this.availabilityRetryTimer);
      this.availabilityRetryTimer = undefined;
    }
  }

  private async loadAvailability(
    view: string,
    sources: Readonly<Record<SourceName, string>>,
    parentSignal?: AbortSignal,
  ): Promise<LoadedRuntimeAvailability> {
    const controller = new AbortController();
    const abort = () => controller.abort(parentSignal?.reason);
    parentSignal?.addEventListener("abort", abort, { once: true });
    if (parentSignal?.aborted) {
      abort();
    }
    const timer = setTimeout(() => {
      controller.abort(new DOMException("Runtime availability timed out", "TimeoutError"));
    }, RUNTIME_AVAILABILITY_TIMEOUT_MS);
    const aborted = new Promise<never>((_resolve, reject) => {
      controller.signal.addEventListener("abort", () => reject(controller.signal.reason), {
        once: true,
      });
      if (controller.signal.aborted) {
        reject(controller.signal.reason);
      }
    });
    try {
      return await Promise.race([
        this.options.loadRuntimeAvailability(view, sources, controller.signal),
        aborted,
      ]);
    } finally {
      clearTimeout(timer);
      parentSignal?.removeEventListener("abort", abort);
    }
  }
}
