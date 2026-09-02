import type {
  BrowserDiagnostic,
  RuntimeStatusPhase,
} from "@marimo-studio/protocol/browser-observations";

export interface PreviewIdentity {
  readonly revision: string;
  readonly sessionId: string | null;
}

export type PreviewAdmissionMessage =
  | { readonly type: "marimo-studio:presentation-change" }
  | {
      readonly type: "marimo-studio:presentation-refresh";
      readonly phase: "pending" | "settled";
    }
  | { readonly type: "marimo-studio:receiver-admitted"; readonly revision: string };

interface RuntimeIdentity {
  readonly revision?: string | null;
  readonly sessionId?: string | null;
}

export interface PreviewAdmissionEffects {
  clearObservations(): void;
  clearSession(): void;
  failView(): void;
  localizedInteractive(identity: PreviewIdentity): void;
  postMessage(message: PreviewAdmissionMessage): void;
  postObservations(): void;
  postSwitch(): void;
  ready(identity: PreviewIdentity): void;
  observation(
    phase: "failed" | "ready" | "synchronizing",
    diagnostics: readonly BrowserDiagnostic[],
    identity: PreviewIdentity,
  ): void;
  status(
    phase: Exclude<RuntimeStatusPhase, "degraded" | "ready">,
    diagnostics: readonly BrowserDiagnostic[],
    identity?: RuntimeIdentity,
  ): void;
  stopControls(): void;
  viewFailed(diagnostic: BrowserDiagnostic, revision: string | null): void;
}

type Owner = "active" | "inactive";
type Receiver =
  | { readonly phase: "unready" }
  | { readonly phase: "ready-unmatched" }
  | { readonly phase: "ready"; readonly revision: string };
type Baseline =
  | { readonly phase: "unknown" }
  | { readonly phase: "known"; readonly revision: string };
type Failure = "fatal" | "localized" | "none";

export interface PreviewAdmissionSnapshot {
  readonly admittedRevision: string | null;
  readonly candidate: PreviewIdentity | null;
  readonly presentation: {
    readonly baseline: Baseline;
    readonly build: "pending" | "settled";
    readonly gate: "pending" | "settled";
    readonly refresh: "acknowledged" | "current" | "requested" | "required";
  };
  readonly ready: PreviewIdentity | null;
  readonly receiver: Receiver;
  readonly requirement: "ordinary" | "required";
  readonly view: "failed" | "ready" | "waiting";
}

const isActive = (owner: Owner): boolean => owner === "active";
const isLocalizedDiagnostic = (diagnostic: BrowserDiagnostic): boolean =>
  diagnostic.scope === "host" || diagnostic.scope === "projection";

export class PreviewAdmission {
  private admittedRevision: string | null = null;
  private candidate: PreviewIdentity | null = null;
  private readyIdentity: PreviewIdentity | null = null;
  private receiver: Receiver = { phase: "unready" };
  private requirement: PreviewAdmissionSnapshot["requirement"] = "ordinary";
  private view: PreviewAdmissionSnapshot["view"] = "waiting";
  private baseline: Baseline = { phase: "unknown" };
  private build: PreviewAdmissionSnapshot["presentation"]["build"] = "settled";
  private gate: PreviewAdmissionSnapshot["presentation"]["gate"] = "settled";
  private refresh: PreviewAdmissionSnapshot["presentation"]["refresh"] = "current";
  private gatedMutationCandidate: PreviewIdentity | undefined;
  private failure: Failure = "none";
  private localizedCommitPending = false;

  constructor(private readonly effects: PreviewAdmissionEffects) {}

  get identity(): PreviewIdentity | null {
    return this.readyIdentity;
  }

  get receiverPresent(): boolean {
    return this.receiver.phase !== "unready";
  }

  get receiverReadyForCurrentView(): boolean {
    return this.receiver.phase === "ready";
  }

  get viewIsReady(): boolean {
    return this.view === "ready";
  }

  get isReady(): boolean {
    return this.view === "ready" && this.hasExactAdmission;
  }

  get isInteractive(): boolean {
    return (
      this.failure !== "fatal" &&
      (this.view === "ready" || this.failure === "localized") &&
      this.hasExactAdmission
    );
  }

  private get hasExactAdmission(): boolean {
    return (
      this.build === "settled" &&
      this.refresh === "current" &&
      this.receiver.phase === "ready" &&
      this.readyIdentity !== null &&
      this.receiver.revision === this.readyIdentity.revision &&
      this.admittedRevision === this.readyIdentity.revision &&
      (this.baseline.phase === "unknown" || this.baseline.revision === this.readyIdentity.revision)
    );
  }

  get snapshot(): PreviewAdmissionSnapshot {
    return {
      admittedRevision: this.admittedRevision,
      candidate: this.candidate,
      presentation: {
        baseline: this.baseline,
        build: this.build,
        gate: this.gate,
        refresh: this.refresh,
      },
      ready: this.readyIdentity,
      receiver: this.receiver,
      requirement: this.requirement,
      view: this.view,
    };
  }

  canObserve(revision: string): boolean {
    return this.isInteractive && this.readyIdentity?.revision === revision;
  }

  resetDocument(): void {
    this.gatedMutationCandidate = undefined;
    this.failure = "none";
    this.localizedCommitPending = false;
    this.admittedRevision = null;
    this.candidate = null;
    this.readyIdentity = null;
    this.receiver = { phase: "unready" };
    this.view = "waiting";
    this.effects.clearSession();
    this.effects.clearObservations();
  }

  requireReady(): void {
    this.requirement = "required";
  }

  reactivate(owner: Owner): void {
    this.refresh = "required";
    this.reconcile(owner);
  }

  buildStarted(owner: Owner, notifyPresentation = true): void {
    if (this.build === "pending") {
      return;
    }
    this.gatedMutationCandidate = undefined;
    const wasAdmitted = this.isInteractive;
    this.clearLocalizedFailure();
    this.localizedCommitPending = false;
    this.build = "pending";
    this.gate = "pending";
    this.admittedRevision = null;
    if (wasAdmitted) {
      this.candidate = this.readyIdentity;
      this.gatedMutationCandidate = notifyPresentation
        ? undefined
        : (this.readyIdentity ?? undefined);
      this.view = "waiting";
      if (isActive(owner)) {
        this.effects.status("synchronizing", []);
      }
    }
    this.effects.stopControls();
    this.effects.clearObservations();
    this.requirement = "required";
    if (notifyPresentation) {
      this.effects.postMessage({ type: "marimo-studio:presentation-refresh", phase: "pending" });
    }
  }

  buildCompleted(revision: string | null, owner: Owner): void {
    this.gatedMutationCandidate = undefined;
    this.build = "settled";
    if (revision !== null) {
      this.baseline = { phase: "known", revision };
    }
    this.reconcile(owner);
  }

  buildUnchanged(owner: Owner): boolean {
    if (this.build !== "pending") {
      return false;
    }
    this.gatedMutationCandidate = undefined;
    this.build = "settled";
    this.reconcile(owner);
    return true;
  }

  streamAbandoned(incompleteBuild = false): void {
    this.invalidateGatedMutationCandidate();
    this.build = "settled";
    if (incompleteBuild) {
      this.baseline = { phase: "unknown" };
      this.refresh = "required";
    }
    this.settleGate();
  }

  presentationChanged(revision: string | null, owner: Owner): void {
    this.invalidateGatedMutationCandidate();
    this.baseline = this.nextBaseline(revision);
    this.refresh = "required";
    if (this.build === "settled") {
      this.reconcile(owner);
    }
  }

  presentationBaseline(revision: string | null, owner: Owner): void {
    if (
      this.gatedMutationCandidate !== undefined &&
      revision !== this.gatedMutationCandidate.revision
    ) {
      this.invalidateGatedMutationCandidate();
    }
    this.baseline = this.nextBaseline(revision);
    if (this.build === "settled") {
      this.reconcile(owner);
    }
  }

  receiverUnready(): void {
    this.invalidateGatedMutationCandidate();
    this.failure = "none";
    this.localizedCommitPending = false;
    this.admittedRevision = null;
    this.candidate = null;
    this.readyIdentity = null;
    this.receiver = { phase: "unready" };
    this.view = "waiting";
    this.refresh =
      this.refresh === "requested" || this.refresh === "acknowledged" ? "acknowledged" : "required";
    this.effects.stopControls();
    this.effects.clearObservations();
    this.effects.clearSession();
    this.effects.status("connecting", [], { revision: null, sessionId: null });
  }

  receiverReady(revision: string, target: "current" | "other", owner: Owner): void {
    this.invalidateGatedMutationCandidate();
    this.failure = "none";
    this.localizedCommitPending = false;
    if (target === "current" && this.refresh === "requested") {
      this.effects.stopControls();
      this.effects.clearSession();
      return;
    }
    const completesRefresh = target === "current" && this.refresh === "acknowledged";
    const sameRevision =
      target === "current" &&
      this.receiver.phase === "ready" &&
      this.receiver.revision === revision;
    this.admittedRevision = sameRevision ? this.admittedRevision : null;
    this.candidate = null;
    this.readyIdentity = null;
    this.receiver =
      target === "current" ? { phase: "ready", revision } : { phase: "ready-unmatched" };
    this.view = "waiting";
    this.effects.stopControls();
    this.effects.clearSession();
    if (target === "current") {
      if (completesRefresh) {
        this.refresh = "current";
      }
      this.effects.status("connecting", [], { revision: null, sessionId: null });
      this.reconcile(owner);
    } else {
      this.refresh = "required";
      if (isActive(owner)) {
        this.effects.postSwitch();
      }
    }
    if (isActive(owner)) {
      this.effects.postObservations();
    }
  }

  viewReady(revision: string, sessionId: string | null, owner: Owner): void {
    this.invalidateGatedMutationCandidate();
    this.failure = "none";
    this.localizedCommitPending = false;
    if (this.refresh === "requested" || this.refresh === "acknowledged") {
      return;
    }
    const identity = { revision, sessionId };
    const sameRevision = this.receiver.phase === "ready" && this.receiver.revision === revision;
    this.admittedRevision = sameRevision ? this.admittedRevision : null;
    this.candidate = identity;
    this.readyIdentity = identity;
    this.receiver = { phase: "ready", revision };
    this.view = "waiting";
    if (
      this.requirement === "required" &&
      this.build === "settled" &&
      this.baseline.phase === "unknown"
    ) {
      this.refresh = "current";
    }
    this.reconcile(owner);
  }

  viewSyncPending(diagnostic: BrowserDiagnostic): void {
    this.invalidateGatedMutationCandidate();
    this.clearLocalizedFailure();
    this.candidate = null;
    this.view = "waiting";
    this.effects.status("synchronizing", [diagnostic]);
  }

  viewError(
    diagnostic: BrowserDiagnostic,
    revision: string | null,
    owner: Owner,
    sessionId?: string | null,
  ): void {
    const previousIdentity = this.readyIdentity;
    if (
      revision !== null &&
      this.receiver.phase === "ready" &&
      this.receiver.revision !== revision
    ) {
      return;
    }
    if (
      revision !== null &&
      previousIdentity?.revision === revision &&
      sessionId !== undefined &&
      previousIdentity.sessionId !== sessionId
    ) {
      return;
    }
    const wasInteractive = this.isInteractive;
    const receiverMatches =
      revision !== null && this.receiver.phase === "ready" && this.receiver.revision === revision;
    if (receiverMatches) {
      if (sessionId !== undefined) {
        this.readyIdentity = { revision: revision!, sessionId };
      } else if (previousIdentity?.revision !== revision) {
        this.readyIdentity = null;
      }
    }
    const baselineMatches =
      revision !== null &&
      (this.baseline.phase === "unknown" || this.baseline.revision === revision);
    const localized =
      revision !== null &&
      receiverMatches &&
      baselineMatches &&
      revision === this.readyIdentity?.revision &&
      this.failure !== "fatal" &&
      isLocalizedDiagnostic(diagnostic);
    const identityChanged =
      localized &&
      (previousIdentity?.revision !== this.readyIdentity?.revision ||
        previousIdentity?.sessionId !== this.readyIdentity?.sessionId);
    this.invalidateGatedMutationCandidate();
    this.failure = localized ? "localized" : "fatal";
    this.localizedCommitPending = localized && (!wasInteractive || identityChanged);
    if (!localized) {
      this.admittedRevision = null;
      this.effects.clearObservations();
      this.effects.stopControls();
    }
    this.candidate = null;
    this.requirement = "ordinary";
    this.view = "failed";
    this.effects.viewFailed(diagnostic, revision);
    if (localized) {
      this.commitLocalizedInteractive(owner);
    } else {
      this.effects.failView();
    }
  }

  mutationError(diagnostic: BrowserDiagnostic, revision: string | null): void {
    const recovery = this.gatedMutationCandidate;
    if (
      this.build !== "pending" ||
      recovery === undefined ||
      revision === null ||
      recovery.revision !== revision ||
      this.candidate !== recovery ||
      this.readyIdentity?.revision !== revision ||
      this.receiver.phase !== "ready" ||
      this.receiver.revision !== revision
    ) {
      return;
    }
    this.failure = "fatal";
    this.localizedCommitPending = false;
    this.view = "failed";
    this.effects.viewFailed(diagnostic, revision);
    this.effects.failView();
  }

  observation(
    state: "error" | "loading" | "ready",
    diagnostics: readonly BrowserDiagnostic[],
    revision: string,
    sessionId: string | null,
  ): void {
    if (!this.observationMatches(revision)) {
      return;
    }
    const identity = { revision, sessionId };
    this.readyIdentity = identity;
    if (state === "ready") {
      this.failure = "none";
      this.localizedCommitPending = false;
      this.view = "ready";
      this.effects.observation("ready", diagnostics, identity);
    } else if (state === "loading") {
      this.clearLocalizedFailure();
      this.view = "waiting";
      this.effects.observation("synchronizing", diagnostics, identity);
    } else {
      const localized =
        this.failure !== "fatal" &&
        diagnostics.length > 0 &&
        diagnostics.every(isLocalizedDiagnostic);
      this.failure = localized ? "localized" : "fatal";
      if (!localized) {
        this.localizedCommitPending = false;
        this.admittedRevision = null;
        this.effects.clearObservations();
        this.effects.stopControls();
      }
      this.view = "failed";
      this.effects.observation("failed", diagnostics, identity);
      if (!localized) {
        this.effects.failView();
      }
    }
  }

  dispose(): void {
    this.gatedMutationCandidate = undefined;
    this.failure = "none";
    this.localizedCommitPending = false;
    this.build = "settled";
    this.settleGate();
  }

  private observationMatches(revision: string): boolean {
    return (
      this.build === "settled" &&
      this.receiver.phase === "ready" &&
      this.readyIdentity?.revision === revision &&
      this.receiver.revision === revision &&
      this.admittedRevision === revision
    );
  }

  private reconcile(owner: Owner): void {
    if (this.receiver.phase !== "ready" || this.build === "pending") {
      return;
    }
    this.settleGate();
    const refreshNeedsBaseline = this.refresh === "required" && this.baseline.phase === "unknown";
    const baselineDiffers =
      this.baseline.phase === "known" && this.baseline.revision !== this.receiver.revision;
    if (refreshNeedsBaseline || baselineDiffers) {
      if (isActive(owner)) {
        this.requestPresentationChange();
      }
      return;
    }
    const fatalWithoutCandidate =
      this.view === "failed" && this.failure === "fatal" && this.candidate === null;
    const retryFatal = fatalWithoutCandidate && this.refresh === "required" && isActive(owner);
    if (fatalWithoutCandidate) {
      if (retryFatal) {
        this.requestPresentationChange();
      }
      return;
    }
    this.refresh = "current";
    this.admittedRevision = this.receiver.revision;
    this.effects.postMessage({
      type: "marimo-studio:receiver-admitted",
      revision: this.receiver.revision,
    });
    this.commitLocalizedInteractive(owner);
    this.commitCandidate();
  }

  private requestPresentationChange(): void {
    this.effects.clearObservations();
    this.clearLocalizedFailure();
    this.localizedCommitPending = false;
    this.effects.status("synchronizing", []);
    this.effects.postMessage({ type: "marimo-studio:presentation-change" });
    this.admittedRevision = null;
    this.candidate = null;
    this.gate = "settled";
    this.refresh = "requested";
    this.requirement = "required";
    this.view = "waiting";
  }

  private commitCandidate(): void {
    if (
      this.build === "pending" ||
      this.candidate === null ||
      this.receiver.phase !== "ready" ||
      this.receiver.revision !== this.candidate.revision ||
      this.admittedRevision !== this.candidate.revision ||
      (this.baseline.phase === "known" && this.baseline.revision !== this.candidate.revision)
    ) {
      return;
    }
    const identity = this.candidate;
    this.candidate = null;
    this.readyIdentity = identity;
    this.failure = "none";
    this.localizedCommitPending = false;
    this.refresh = "current";
    this.requirement = "ordinary";
    this.view = "ready";
    this.effects.ready(identity);
  }

  private clearLocalizedFailure(): void {
    if (this.failure === "localized") {
      this.failure = "none";
    }
  }

  private settleGate(): void {
    if (this.gate === "settled") {
      return;
    }
    this.gate = "settled";
    this.effects.postMessage({ type: "marimo-studio:presentation-refresh", phase: "settled" });
  }

  private commitLocalizedInteractive(owner: Owner): void {
    const identity = this.readyIdentity;
    if (
      !this.localizedCommitPending ||
      !isActive(owner) ||
      !this.isInteractive ||
      identity === null
    ) {
      return;
    }
    this.localizedCommitPending = false;
    this.effects.localizedInteractive(identity);
  }

  private invalidateGatedMutationCandidate(): void {
    const recovery = this.gatedMutationCandidate;
    this.gatedMutationCandidate = undefined;
    if (recovery !== undefined && this.candidate === recovery) {
      this.candidate = null;
    }
  }

  private nextBaseline(revision: string | null): Baseline {
    return revision === null ? { phase: "unknown" } : { phase: "known", revision };
  }
}
