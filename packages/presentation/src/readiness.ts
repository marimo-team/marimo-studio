import type { PresentationDiagnostic, RuntimeDiagnostic } from "./diagnostics.ts";

export type RuntimeConnectionState = "connecting" | "ready" | "error";
export type PresentationRefreshState = "ready" | "loading" | "error";
export type PageReadinessState = "connecting" | "loading" | "ready" | "error";

export interface ReadinessSnapshot {
  readonly connection: RuntimeConnectionState;
  readonly presentation: PresentationRefreshState;
  readonly page: PageReadinessState;
  readonly settled: boolean;
  readonly runtimeDiagnostic?: RuntimeDiagnostic;
  readonly presentationDiagnostic?: PresentationDiagnostic;
}

interface Deferred {
  promise: Promise<void>;
  resolve: () => void;
}

const deferred = (): Deferred => {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

export const pageReadinessState = (
  connection: RuntimeConnectionState,
  hostStates: readonly string[],
  presentation: PresentationRefreshState = "ready",
): PageReadinessState => {
  if (connection === "error" || presentation === "error") {
    return "error";
  }
  if (connection !== "ready") {
    return "connecting";
  }
  if (presentation === "loading") {
    return "loading";
  }
  if (hostStates.some((state) => ["connecting", "loading", "stale"].includes(state))) {
    return "loading";
  }
  if (hostStates.some((state) => ["error", "missing"].includes(state))) {
    return "error";
  }
  return "ready";
};

type Listener = (snapshot: ReadinessSnapshot, previous: ReadinessSnapshot) => void;

export class ReadinessController {
  private connection: RuntimeConnectionState = "connecting";
  private presentation: PresentationRefreshState = "ready";
  private runtimeDiagnostic: RuntimeDiagnostic | undefined;
  private presentationDiagnostic: PresentationDiagnostic | undefined;
  private hostStates: readonly string[] = [];
  private presentationGeneration = 0;
  private waiter = deferred();
  private snapshotValue: ReadinessSnapshot = {
    connection: "connecting",
    presentation: "ready",
    page: "connecting",
    settled: false,
  };
  private readonly listeners = new Set<Listener>();

  start(): void {
    this.connection = "connecting";
    this.presentation = "ready";
    this.runtimeDiagnostic = undefined;
    this.presentationDiagnostic = undefined;
    this.hostStates = [];
    this.presentationGeneration = 0;
    this.waiter = deferred();
    this.commit();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): ReadinessSnapshot {
    return this.snapshotValue;
  }

  ready(): Promise<void> {
    return this.snapshotValue.settled ? Promise.resolve() : this.waiter.promise;
  }

  setHosts(states: readonly string[]): void {
    if (
      states.length === this.hostStates.length &&
      states.every((state, index) => state === this.hostStates[index])
    ) {
      return;
    }
    this.hostStates = [...states];
    this.commit();
  }

  setRuntime(state: RuntimeConnectionState, diagnostic?: RuntimeDiagnostic): void {
    this.connection = state;
    if (diagnostic !== undefined) {
      this.runtimeDiagnostic = diagnostic;
    } else if (state === "ready") {
      this.runtimeDiagnostic = undefined;
    }
    this.commit();
  }

  beginPresentation(): number {
    this.presentationGeneration += 1;
    this.presentation = "loading";
    this.presentationDiagnostic = undefined;
    this.commit();
    return this.presentationGeneration;
  }

  setPresentation(
    generation: number,
    state: PresentationRefreshState,
    diagnostic?: PresentationDiagnostic,
  ): void {
    if (generation !== this.presentationGeneration) {
      return;
    }
    this.presentation = state;
    this.presentationDiagnostic = diagnostic;
    this.commit();
  }

  private commit(): void {
    const previous = this.snapshotValue;
    const page = pageReadinessState(this.connection, this.hostStates, this.presentation);
    const settled =
      this.connection === "error" ||
      this.presentation === "error" ||
      (this.connection === "ready" &&
        this.presentation === "ready" &&
        !this.hostStates.some((state) => ["connecting", "loading", "stale"].includes(state)));
    if (!settled && previous.settled) {
      this.waiter = deferred();
    }
    this.snapshotValue = {
      connection: this.connection,
      presentation: this.presentation,
      page,
      settled,
      runtimeDiagnostic: this.runtimeDiagnostic,
      presentationDiagnostic: this.presentationDiagnostic,
    };
    if (settled && !previous.settled) {
      this.waiter.resolve();
    }
    this.listeners.forEach((listener) => listener(this.snapshotValue, previous));
  }
}

export const readiness = new ReadinessController();

export const beginPresentationRefresh = (): number => readiness.beginPresentation();

export const setPresentationRefreshState = (
  generation: number,
  state: PresentationRefreshState,
  diagnostic?: PresentationDiagnostic,
): void => readiness.setPresentation(generation, state, diagnostic);
