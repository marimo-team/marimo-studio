import type { RuntimeProgress } from "@marimo-studio/protocol/runtime-progress";
import type {
  BrowserDiagnostic,
  RuntimeStatusPhase,
  RuntimeStatusReport,
} from "@marimo-studio/protocol/runtime-status";

import {
  parsePreviewMessage,
  type PresentationToStudioMessage,
  type SwitchViewMessage,
  type ViewNavigationIntent,
  type ViewDiagnostic,
  type ViewPreviewMessage,
} from "@marimo-studio/protocol/preview-messages";
import {
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";

import type { PreviewAdmissionMessage, PreviewIdentity } from "./admission.ts";
import type { ControlFrameConnector, ControlSyncStatus } from "./control-sync.ts";
import type { EditorQuerySyncResult } from "./query-remote.ts";

import { assertNever } from "../../shared/assertNever.ts";
import { errorMessage } from "../../shared/errors.ts";
import { PreviewAdmission } from "./admission.ts";
import { PreviewControlController } from "./control-controller.ts";
import { fetchRuntimeControls } from "./control-remote.ts";
import { releaseFrameBridge, resizeFrame } from "./frame-bridge.ts";
import { PreviewMutationBarriers } from "./mutation-barriers.ts";
import { PreviewQueryController, type QuerySyncStatus } from "./query-controller.ts";
import { RetrySchedule } from "./retry-schedule.ts";
import { RuntimeDiagnostics } from "./runtime-diagnostics.ts";
import { previewStatus, type PreviewStatus } from "./status.ts";

export interface PreviewFrameState {
  rendered: boolean;
  progress: RuntimeProgress | null;
  url: string;
  lifecycleId: number;
  status: PreviewStatus;
  runtimeStatus: RuntimeStatusReport;
}

interface RuntimeStatusIdentity {
  revision?: string | null;
  sessionId?: string | null;
}

interface PendingViewSwitch {
  readonly lifecycleId: number;
  readonly view: string;
  readonly resolve: (ready: boolean) => void;
  readonly timer: ReturnType<typeof setTimeout>;
  readonly signal?: AbortSignal;
  readonly abort?: () => void;
}

let previewDocumentLifecycleSequence = 1;
// Leave the activation coordinator time to acknowledge the ready document
// before the server's 120-second request deadline.
const VIEW_SWITCH_TIMEOUT_MS = 100_000;

export const nextPreviewDocumentLifecycleId = (): number => ++previewDocumentLifecycleSequence;

export const previewDocumentUrl = (url: string, lifecycleId: number): string => {
  const target = new URL(url, globalThis.location.href);
  target.searchParams.set(DOCUMENT_LIFECYCLE_QUERY_PARAM, String(lifecycleId));
  return target.toString();
};

export class PreviewController {
  private readonly view: string;
  private state: PreviewFrameState;
  private readonly admission: PreviewAdmission;
  private diagnostics: ViewDiagnostic[] = [];
  private controlDiagnostic: BrowserDiagnostic | undefined;
  private queryDiagnostic: BrowserDiagnostic | undefined;
  private queryPhase: QuerySyncStatus["phase"] = "ready";
  private activationsInProgress = 0;
  private activationGeneration = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private readonly retrySchedule = new RetrySchedule();
  private editorSessionId: string | undefined;
  private navigation: ViewNavigationIntent;
  private pendingViewSwitch: PendingViewSwitch | undefined;
  private activeLifecycleId: number;
  private waitingLifecycleId: number | undefined;
  private activeOwner = true;
  private readonly mutationBarriers: PreviewMutationBarriers;
  private readonly runtimeDiagnostics: RuntimeDiagnostics;
  private readonly controls: PreviewControlController;
  private readonly queries: PreviewQueryController;

  constructor(
    initialView: string,
    private readonly runtime: string,
    private readonly editor: HTMLIFrameElement,
    private readonly preview: HTMLIFrameElement,
    private readonly viewUrl: (
      view: string,
      runtime: string,
      navigation?: ViewNavigationIntent,
    ) => string,
    private readonly supportUrl: (view: string) => string,
    syncQuery: (query: string) => void,
    syncEditorQuery: (
      query: string,
      operationId: string,
      writeGeneration: number,
      signal: AbortSignal,
    ) => Promise<EditorQuerySyncResult>,
    private readonly navigate: (view: string, intent: ViewNavigationIntent) => Promise<boolean>,
    private readonly report: (state: PreviewFrameState) => void,
    connectControlFrame?: ControlFrameConnector,
    initialNavigation: ViewNavigationIntent = {
      query: globalThis.location.search,
      hash: globalThis.location.hash,
    },
    private readonly navigationQueryChanged?: (query: string) => void,
    initialLifecycleId = 1,
    private readonly nextLifecycleId: () => number = nextPreviewDocumentLifecycleId,
    initialEditorSessionId?: string,
  ) {
    this.view = initialView;
    this.navigation = initialNavigation;
    this.activeLifecycleId = initialLifecycleId;
    this.editorSessionId = initialEditorSessionId;
    this.preview.dataset.previewLifecycleId = String(initialLifecycleId);
    this.runtimeDiagnostics = new RuntimeDiagnostics({ runtime, view: initialView });
    const runtimeStatus = this.runtimeDiagnostics.report();
    this.state = {
      rendered: false,
      progress: null,
      url: this.viewUrl(initialView, runtime, this.navigation),
      lifecycleId: this.activeLifecycleId,
      status: previewStatus(runtime, runtimeStatus.current),
      runtimeStatus,
    };
    this.controls = new PreviewControlController({
      runtime,
      editor,
      preview,
      supportUrl: () => this.supportUrl(this.view),
      clientId: () =>
        new URL(
          this.viewUrl(this.view, this.runtime, this.navigation),
          globalThis.location.href,
        ).searchParams.get(STUDIO_CLIENT_QUERY_PARAM) ?? undefined,
      connect: connectControlFrame,
      fetchControls: fetchRuntimeControls,
      status: (status, revision, sessionId) =>
        this.controlStatusChanged(status, revision, sessionId),
    });
    this.queries = new PreviewQueryController(
      runtime,
      preview,
      syncQuery,
      syncEditorQuery,
      () => {
        const query = this.queries.currentQuery;
        this.navigation = { ...this.navigation, query };
        this.navigationQueryChanged?.(query);
        this.setPopoutUrl(this.viewUrl(this.view, this.runtime, this.navigation));
      },
      this.navigation.query,
      (status) => this.queryStatusChanged(status),
    );
    this.admission = new PreviewAdmission({
      clearSession: () => delete this.preview.dataset.sessionId,
      failView: () => this.completeViewSwitch(false, this.activeLifecycleId),
      localizedInteractive: (identity) => {
        this.state = { ...this.state, rendered: true };
        this.setPreviewSession(identity);
        this.completeViewSwitch(true, this.activeLifecycleId);
        if (this.activeOwner && this.activationsInProgress === 0) {
          this.controls.begin(
            identity.revision,
            identity.sessionId ?? undefined,
            this.editorSessionId,
          );
        }
        this.report(this.state);
      },
      postMessage: (message) => this.postAdmissionMessage(message),
      postSwitch: () => this.postSwitch(),
      ready: (identity) => this.commitReadyIdentity(identity),
      status: (phase, diagnostics, identity) => this.setRuntimeStatus(phase, diagnostics, identity),
      stopControls: () => this.controls.stop(),
      viewFailed: (diagnostic, revision) => {
        const identity =
          revision !== null && this.admission.identity?.revision === revision
            ? this.admission.identity
            : null;
        if (identity !== null) {
          this.setPreviewSession(identity);
        }
        let statusIdentity = {};
        if (revision !== null) {
          statusIdentity =
            identity === null ? { revision } : { revision, sessionId: identity.sessionId };
        }
        this.setRuntimeStatus("failed", [diagnostic], statusIdentity);
      },
    });
    this.mutationBarriers = new PreviewMutationBarriers({
      runtime,
      view: initialView,
      frame: preview,
      active: () => this.activeOwner,
      lifecycleId: () => this.activeLifecycleId,
      receiver: () => {
        if (!this.admission.receiverPresent) {
          return "absent";
        }
        return this.admission.receiverReadyForCurrentView ? "ready" : "other";
      },
    });
    this.bind();
  }

  waitUntilReady(signal?: AbortSignal): Promise<boolean> {
    if (!this.activeOwner || signal?.aborted) {
      return Promise.resolve(false);
    }
    if (this.admission.isInteractive) {
      return Promise.resolve(true);
    }
    this.completeViewSwitch(false, this.pendingViewSwitch?.lifecycleId);
    return this.waitForView(this.view, this.activeLifecycleId, signal);
  }

  activateDocument(navigation: ViewNavigationIntent, reload = false): void {
    const rendered = this.activate(navigation, undefined, reload);
    const activationGeneration = this.activationGeneration;
    const lifecycleId = this.activeLifecycleId;
    void rendered
      .then((ready) => {
        if (!ready && this.admission.snapshot.view !== "failed")
          throw new Error("The preview did not become ready before activation completed.");
      })
      .catch((cause: unknown) => {
        if (
          !this.activeOwner ||
          this.activeLifecycleId !== lifecycleId ||
          this.activationGeneration !== activationGeneration
        )
          return;
        this.admission.viewError(
          this.lifecycleDiagnostic(
            "preview-activation-failed",
            "error",
            errorMessage(cause),
            "Reload the preview to retry.",
          ),
          this.admission.identity?.revision ?? null,
          this.admissionOwner(),
        );
      });
  }

  async activate(
    navigation: ViewNavigationIntent,
    signal?: AbortSignal,
    reload = false,
  ): Promise<boolean> {
    if (signal?.aborted) {
      return false;
    }
    this.activationGeneration += 1;
    this.activationsInProgress += 1;
    try {
      const reactivating = !this.activeOwner;
      this.activeOwner = true;
      this.navigation = navigation;
      this.queries.commitNavigation(navigation.query);
      if (reload) {
        this.admission.requireReady();
        this.reload();
      } else if (reactivating) {
        this.admission.reactivate(this.admissionOwner());
      }
      if (this.preview.src === "about:blank") {
        this.reloadCurrentDocument();
      }
      const lifecycleId = this.activeLifecycleId;
      const ready = await this.waitUntilReady(signal);
      if (!ready || !this.activeOwner || this.activeLifecycleId !== lifecycleId) {
        return false;
      }
      const identity = this.admission.identity;
      if (this.admission.isInteractive && identity !== null) {
        await this.queries.applyToPreview(true, navigation.hash);
        if (!this.activeOwner || this.activeLifecycleId !== lifecycleId) {
          return false;
        }
        this.controls.begin(
          identity.revision,
          identity.sessionId ?? undefined,
          this.editorSessionId,
        );
      }
      return true;
    } finally {
      this.activationsInProgress -= 1;
    }
  }

  deactivate(): void {
    if (!this.activeOwner) {
      return;
    }
    this.mutationBarriers.retire(
      new DOMException("The presentation was deactivated.", "AbortError"),
    );
    this.activeOwner = false;
    this.completeViewSwitch(false, this.pendingViewSwitch?.lifecycleId);
    this.cancelRetry();
    this.controls.stop();
    this.controlDiagnostic = undefined;
    this.queries.cancel();
    this.queryDiagnostic = undefined;
    this.queryPhase = "ready";
  }

  navigateWithinView(navigation: ViewNavigationIntent): void {
    this.navigation = navigation;
    this.queries.commitNavigation(navigation.query);
    if (!this.activeOwner) {
      return;
    }
    void this.queries.applyToPreview(this.admission.isInteractive, navigation.hash);
    const next = this.viewUrl(this.view, this.runtime, this.navigation);
    this.setPopoutUrl(next);
  }

  synchronizeNavigationQuery(query: string): Promise<boolean> {
    return this.activeOwner ? this.queries.synchronizeNavigation(query) : Promise.resolve(false);
  }

  cancelNavigation(): void {
    this.queries.cancelNavigation();
  }

  rollbackNavigation(query?: string): Promise<boolean> {
    return this.queries.rollbackNavigation(query);
  }

  requestResize(): void {
    resizeFrame(this.preview);
  }

  runtimeStatus(): RuntimeStatusReport {
    return this.runtimeDiagnostics.report();
  }

  readyForInteraction(): boolean {
    return this.admission.isInteractive;
  }

  editorSessionChanged(sessionId?: string, reload = true): void {
    this.editorSessionId = sessionId;
    if (!this.activeOwner) {
      return;
    }
    if (reload) {
      this.reload();
      return;
    }
    const identity = this.admission.identity;
    if (this.admission.isInteractive && identity !== null) {
      this.controls.begin(identity.revision, identity.sessionId ?? undefined, this.editorSessionId);
    }
  }

  presentationBuildStarted(): void {
    this.admission.buildStarted(this.admissionOwner());
  }

  presentationBuildCompleted(revision: string | null, diagnostic?: BrowserDiagnostic): void {
    this.admission.buildCompleted(revision, this.admissionOwner(), diagnostic);
  }

  notebookMutationPending(generation: number, enterAdmission: boolean): Promise<() => boolean> {
    if (enterAdmission) {
      this.admission.buildStarted(this.admissionOwner(), false);
    }
    return this.mutationBarriers
      .pause(generation)
      .then(() => () => this.admission.buildUnchanged(this.admissionOwner()));
  }

  notebookMutationSaveFailed(active: boolean): void {
    if (!active) {
      return;
    }
    this.admission.mutationError(
      {
        code: "notebook-save-failed",
        severity: "error",
        message: "Notebook save failed.",
        hint: "Retry the save to update this view.",
        view: this.view,
        scope: "runtime",
      },
      this.admission.identity?.revision ?? null,
    );
  }

  notebookMutationTransactionFailed(active: boolean): void {
    if (!active) {
      return;
    }
    this.admission.mutationError(
      {
        code: "notebook-sync-failed",
        severity: "error",
        message: "Notebook change could not be synchronized.",
        hint: "Retry the edit to update this view.",
        view: this.view,
        scope: "runtime",
      },
      this.admission.identity?.revision ?? null,
    );
  }

  presentationStreamAbandoned(incompleteBuild = false): void {
    this.admission.streamAbandoned(incompleteBuild);
  }

  presentationChanged(revision?: string): void {
    this.retireProgress();
    this.admission.presentationChanged(revision ?? null, this.admissionOwner());
  }

  presentationBaseline(revision: string | null): void {
    const baseline = this.admission.snapshot.presentation.baseline;
    if (baseline.phase === "known" && baseline.revision !== revision) {
      this.retireProgress();
    }
    this.admission.presentationBaseline(revision, this.admissionOwner());
  }

  private retireProgress(): void {
    if (this.state.progress !== null) {
      this.state = { ...this.state, progress: null };
      this.report(this.state);
    }
  }

  private admissionOwner(): "active" | "inactive" {
    return this.activeOwner ? "active" : "inactive";
  }

  private postAdmissionMessage(message: PreviewAdmissionMessage): void {
    this.preview.contentWindow?.postMessage(
      {
        ...message,
        runtime: this.runtime,
        lifecycleId: this.activeLifecycleId,
        view: this.view,
      },
      "*",
    );
  }

  private commitReadyIdentity(identity: PreviewIdentity): void {
    this.state = { ...this.state, rendered: true };
    this.setPreviewSession(identity);
    this.showReadyStatus();
    if (!this.activeOwner) {
      return;
    }
    this.completeViewSwitch(true, this.activeLifecycleId);
    this.controls.begin(identity.revision, identity.sessionId ?? undefined, this.editorSessionId);
  }

  private setPreviewSession(identity: PreviewIdentity): void {
    if (identity.sessionId === null) {
      delete this.preview.dataset.sessionId;
    } else {
      this.preview.dataset.sessionId = identity.sessionId;
    }
  }

  editorQueryChanged(query: string, operationId?: string, completed = false): void {
    if (this.activeOwner) {
      this.queries.editorChanged(query, this.admission.isInteractive, operationId, completed);
    }
  }

  dispose(): void {
    this.activeOwner = false;
    this.mutationBarriers.retire(new DOMException("The presentation was disposed.", "AbortError"));
    this.admission.dispose();
    this.completeViewSwitch(false, this.pendingViewSwitch?.lifecycleId);
    this.cancelRetry();
    this.controls.stop();
    this.controlDiagnostic = undefined;
    this.queries.cancel();
    releaseFrameBridge(this.preview);
    this.editor.removeEventListener("load", this.startFromEditor);
    this.preview.removeEventListener("load", this.previewLoaded);
    globalThis.removeEventListener("message", this.message);
  }

  private bind(): void {
    globalThis.addEventListener("message", this.message);
    this.preview.addEventListener("load", this.previewLoaded);
    this.editor.addEventListener("load", this.startFromEditor, { once: true });
    if (this.editor.contentDocument?.readyState === "complete") {
      this.startFromEditor();
    }
  }

  private readonly startFromEditor = (): void => {
    this.editor.removeEventListener("load", this.startFromEditor);
    if (this.preview.src === "about:blank") {
      this.reloadCurrentDocument();
    }
  };

  private readonly message = (event: MessageEvent<unknown>) => {
    if (
      (event.origin !== "null" && event.origin !== globalThis.location.origin) ||
      event.source !== this.preview.contentWindow
    ) {
      return;
    }
    const message = parsePreviewMessage(event.data);
    if (
      !message ||
      message.type === "marimo-studio:switch-view" ||
      message.type === "marimo-studio:presentation-change" ||
      message.type === "marimo-studio:presentation-refresh" ||
      message.type === "marimo-studio:presentation-refresh-barrier" ||
      message.type === "marimo-studio:replay-document" ||
      message.type === "marimo-studio:restore-fragment" ||
      message.type === "marimo-studio:receiver-admitted" ||
      message.runtime !== this.runtime
    ) {
      return;
    }
    if (!this.acceptsSwitchAcknowledgement(message)) {
      return;
    }
    if (
      !this.activeOwner &&
      (message.type === "marimo-studio:navigate-view" ||
        message.type === "marimo-studio:query-change")
    ) {
      return;
    }
    this.receive(message);
  };

  private receive(message: PresentationToStudioMessage): void {
    switch (message.type) {
      case "marimo-studio:view-progress": {
        const baseline = this.admission.snapshot.presentation.baseline;
        if (
          message.view === this.view &&
          (baseline.phase === "unknown" || message.revision === baseline.revision) &&
          this.state.status.state === "loading"
        ) {
          this.state = {
            ...this.state,
            progress: message.progress ?? { message: this.state.status.message },
          };
          this.report(this.state);
        }
        return;
      }
      case "marimo-studio:navigate-view":
        void this.navigate(message.view, { query: message.query, hash: message.hash });
        return;
      case "marimo-studio:query-change":
        this.previewQueryChanged(message.query);
        return;
      case "marimo-studio:receiver-unready":
        this.waitingLifecycleId = undefined;
        this.controlDiagnostic = undefined;
        this.mutationBarriers.retire(
          new DOMException("The presentation receiver disconnected.", "AbortError"),
          true,
        );
        this.admission.receiverUnready();
        return;
      case "marimo-studio:receiver-waiting":
        this.waitingLifecycleId = message.lifecycleId;
        this.cancelRetry();
        return;
      case "marimo-studio:receiver-ready":
        this.waitingLifecycleId = undefined;
        this.controlDiagnostic = undefined;
        this.cancelRetry();
        this.retrySchedule.reset();
        this.admission.receiverReady(
          message.revision,
          message.view === this.view ? "current" : "other",
          this.admissionOwner(),
        );
        if (message.view === this.view) {
          this.mutationBarriers.receiverReady();
        } else {
          this.mutationBarriers.retire(
            new DOMException("The presentation receiver changed views.", "AbortError"),
          );
        }
        return;
      case "marimo-studio:view-ready":
      case "marimo-studio:view-sync-pending":
      case "marimo-studio:view-diagnostics":
      case "marimo-studio:view-error":
        if (message.view === this.view) {
          this.receiveView(message);
        }
        return;
      default:
        assertNever(message);
    }
  }

  private receiveView(message: ViewPreviewMessage): void {
    switch (message.type) {
      case "marimo-studio:view-ready":
        this.admission.viewReady(
          message.revision,
          message.sessionId ?? null,
          this.admissionOwner(),
        );
        return;
      case "marimo-studio:view-sync-pending":
        this.admission.viewSyncPending(message.diagnostic);
        return;
      case "marimo-studio:view-diagnostics":
        this.diagnostics = message.diagnostics;
        if (this.admission.viewIsReady) {
          this.showReadyStatus();
        }
        return;
      case "marimo-studio:view-error":
        this.admission.viewError(
          message.diagnostic,
          message.revision ?? null,
          this.admissionOwner(),
          message.sessionId,
        );
        return;
      default:
        assertNever(message);
    }
  }

  private previewQueryChanged(query: string): void {
    if (this.activeOwner) {
      this.queries.previewChanged(query);
    }
  }

  private postSwitch(): void {
    if (!this.activeOwner) {
      return;
    }
    const message: SwitchViewMessage = {
      type: "marimo-studio:switch-view",
      runtime: this.runtime,
      view: this.view,
      lifecycleId: this.activeLifecycleId,
      documentUrl: previewDocumentUrl(
        this.viewUrl(this.view, this.runtime, this.navigation),
        this.activeLifecycleId,
      ),
      supportUrl: this.supportUrl(this.view),
    };
    this.preview.contentWindow?.postMessage(message, "*");
  }

  private waitForView(view: string, lifecycleId: number, signal?: AbortSignal): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = setTimeout(
        () => this.completeViewSwitch(false, lifecycleId),
        VIEW_SWITCH_TIMEOUT_MS,
      );
      const abort = signal ? () => this.completeViewSwitch(false, lifecycleId) : undefined;
      if (signal && abort) {
        signal.addEventListener("abort", abort, { once: true });
      }
      this.pendingViewSwitch = { lifecycleId, view, resolve, timer, signal, abort };
    });
  }

  private completeViewSwitch(ready: boolean, lifecycleId: number | undefined): void {
    const pending = this.pendingViewSwitch;
    if (!pending || pending.lifecycleId !== lifecycleId) {
      return;
    }
    clearTimeout(pending.timer);
    if (pending.signal && pending.abort) {
      pending.signal.removeEventListener("abort", pending.abort);
    }
    this.pendingViewSwitch = undefined;
    pending.resolve(ready && pending.view === this.view);
  }

  private acceptsSwitchAcknowledgement(message: PresentationToStudioMessage): boolean {
    return message.lifecycleId === this.activeLifecycleId;
  }

  reload(): void {
    if (!this.activeOwner) {
      return;
    }
    this.mutationBarriers.retire(
      new DOMException("The presentation document changed.", "AbortError"),
    );
    this.completeViewSwitch(false, this.pendingViewSwitch?.lifecycleId);
    this.setActiveLifecycle(this.nextLifecycleId());
    this.state = { ...this.state, lifecycleId: this.activeLifecycleId };
    this.reloadCurrentDocument();
  }

  private reloadCurrentDocument(): void {
    this.state = { ...this.state, rendered: false, progress: null };
    this.cancelRetry();
    this.controls.stop();
    this.controlDiagnostic = undefined;
    this.queries.cancel();
    releaseFrameBridge(this.preview);
    this.admission.resetDocument();
    this.setRuntimeStatus("connecting", [], {
      revision: null,
      sessionId: null,
    });
    const next = this.viewUrl(this.view, this.runtime, this.navigation);
    this.setPopoutUrl(next);
    this.navigatePreview(previewDocumentUrl(next, this.activeLifecycleId));
  }

  private setPopoutUrl(url: string): void {
    this.state = { ...this.state, url };
    this.report(this.state);
  }

  private navigatePreview(next: string): void {
    this.preview.src = next;
  }

  private loaded(): void {
    if (
      !this.activeOwner ||
      this.admission.receiverPresent ||
      this.waitingLifecycleId === this.activeLifecycleId ||
      this.preview.src === "about:blank"
    ) {
      return;
    }
    this.scheduleRetry(10_000);
  }

  private readonly previewLoaded = (): void => {
    if (!this.activeOwner) {
      return;
    }
    this.loaded();
    const identity = this.admission.identity;
    if (this.admission.isInteractive && identity !== null) {
      this.controls.begin(identity.revision, identity.sessionId ?? undefined, this.editorSessionId);
    }
  };

  private showReadyStatus(): void {
    const diagnostics = [
      ...this.diagnostics,
      ...(this.controlDiagnostic ? [this.controlDiagnostic] : []),
      ...(this.queryDiagnostic ? [this.queryDiagnostic] : []),
    ];
    let phase: RuntimeStatusPhase = "ready";
    if (this.queryPhase === "synchronizing") {
      phase = "synchronizing";
    } else if (diagnostics.length > 0) {
      phase = "degraded";
    }
    this.setRuntimeStatus(phase, diagnostics, {
      revision: this.admission.identity?.revision ?? null,
      sessionId: this.admission.identity?.sessionId ?? null,
    });
  }

  private queryStatusChanged(status: QuerySyncStatus): void {
    if (!this.activeOwner) {
      return;
    }
    this.queryPhase = status.phase;
    this.queryDiagnostic =
      status.phase === "degraded"
        ? this.lifecycleDiagnostic(
            "query-sync-failed",
            "warning",
            "Query state could not be synchronized.",
            status.error?.message ?? "Retry the current query.",
          )
        : undefined;
    if (this.admission.viewIsReady) {
      this.showReadyStatus();
    }
  }

  private controlStatusChanged(
    status: ControlSyncStatus,
    revision: string,
    sessionId: string | undefined,
  ): void {
    if (
      !this.activeOwner ||
      !this.admission.viewIsReady ||
      revision !== this.admission.identity?.revision ||
      sessionId !== (this.admission.identity?.sessionId ?? undefined)
    ) {
      return;
    }
    this.controlDiagnostic =
      status.phase === "degraded"
        ? this.lifecycleDiagnostic(
            "control-sync-failed",
            "warning",
            "Control state could not be synchronized.",
            status.error?.message ?? "Wait for both notebook runtimes, then retry the view.",
          )
        : undefined;
    this.showReadyStatus();
  }

  private setRuntimeStatus(
    phase: RuntimeStatusPhase,
    diagnostics: readonly BrowserDiagnostic[],
    identity: RuntimeStatusIdentity = {},
  ): void {
    this.updateRuntimeStatus(this.runtimeDiagnostics.record({ phase, diagnostics, ...identity }));
  }

  private updateRuntimeStatus(runtimeStatus: RuntimeStatusReport, url = this.state.url): void {
    this.state = {
      ...this.state,
      progress:
        runtimeStatus.current.phase === "connecting" ||
        runtimeStatus.current.phase === "synchronizing"
          ? this.state.progress
          : null,
      url,
      lifecycleId: this.activeLifecycleId,
      runtimeStatus,
      status: previewStatus(this.runtime, runtimeStatus.current),
    };
    this.report(this.state);
  }

  private lifecycleDiagnostic(
    code: string,
    severity: BrowserDiagnostic["severity"],
    message: string,
    hint: string,
  ): BrowserDiagnostic {
    return {
      code,
      severity,
      message,
      hint,
      view: this.view,
      scope: "runtime",
    };
  }

  private scheduleRetry(delay = this.retrySchedule.next()): void {
    if (!this.activeOwner) {
      return;
    }
    this.cancelRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      if (this.activeOwner && !this.admission.receiverPresent) {
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

  private setActiveLifecycle(lifecycleId: number): void {
    this.activeLifecycleId = lifecycleId;
    this.waitingLifecycleId = undefined;
    this.preview.dataset.previewLifecycleId = String(lifecycleId);
  }
}
