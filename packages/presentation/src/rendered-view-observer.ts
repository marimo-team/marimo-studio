import type {
  ViewErrorMessage,
  ViewReadyMessage,
  ViewSyncPendingMessage,
} from "@marimo-studio/protocol/preview-messages";
import type { ObservedProjectionInstance } from "@marimo-studio/protocol/projections";

import type { RuntimeDiagnostic, StudioDiagnostic } from "./diagnostics.ts";

import { documentLifecycleEnvelope } from "./document/document-lifecycle-id.ts";
import { postToStudioParent } from "./document/parent-bridge.ts";
import { studioOwned } from "./document/studio-ownership.ts";
import { projectionHosts } from "./projections/host-runtime.ts";
import { renderedProjectionInstances } from "./projections/instances.ts";
import { toBrowserDiagnostic } from "./readiness-diagnostics.ts";
import { type ReadinessSnapshot, readiness, type RuntimeConnectionState } from "./readiness.ts";
import { renderedViewDiagnostics, renderedViewIdentity } from "./rendered-view-state.ts";
import { getRuntimeConfig } from "./runtime-config/index.ts";
import { viewStyleDiagnostic } from "./view-styles/runtime.ts";

export interface RuntimeStateDescription {
  readonly fingerprint: string;
  readonly aliases: readonly string[];
  readonly inputs: Readonly<Record<string, JsonValue>>;
}

export interface RuntimeStateApi {
  inputs(): Readonly<Record<string, JsonValue>>;
  states(): readonly RuntimeStateDescription[];
  update(patch: Readonly<Record<string, JsonValue>>): Promise<void>;
}

interface MarimoStudioApi {
  ready: () => Promise<void>;
  diagnostics: () => readonly StudioDiagnostic[];
  identity: () => { readonly projectionRevision: string; readonly revision: string };
  projections: () => readonly ObservedProjectionInstance[];
  updateQuery: (query: string) => Promise<void>;
  state?: RuntimeStateApi;
}

let observer: MutationObserver | undefined;
let stopProjectionChanges: (() => void) | undefined;
let stopReadinessChanges: (() => void) | undefined;
let generation = 0;
let pendingEvaluation: number | undefined;
let ownedRuntimeDiagnosticHost: HTMLElement | undefined;

const runtimeDiagnosticHost = (): HTMLElement => {
  if (ownedRuntimeDiagnosticHost?.isConnected) {
    return ownedRuntimeDiagnosticHost;
  }
  const host = document.createElement("div");
  host.dataset.marimoStudioRuntimeDiagnostic = "";
  host.setAttribute("role", "alert");
  host.hidden = true;
  document.body.append(host);
  ownedRuntimeDiagnosticHost = host;
  return ownedRuntimeDiagnosticHost;
};

const publishRuntimeDiagnostic = (diagnostic?: RuntimeDiagnostic): void => {
  const host = runtimeDiagnosticHost();
  if (!diagnostic) {
    host.hidden = true;
    return;
  }
  host.textContent = diagnostic.message;
  host.dataset.state = diagnostic.severity === "warning" ? "waiting" : "error";
  host.setAttribute("role", diagnostic.severity === "warning" ? "status" : "alert");
  host.title = diagnostic.hint;
  host.hidden = diagnostic.severity === "warning" && studioOwned();
  const view = renderedViewIdentity();
  const identity = {
    runtime: view.runtime,
    ...documentLifecycleEnvelope(),
    diagnostic: toBrowserDiagnostic(diagnostic),
    view: diagnostic.view,
  };
  let message: ViewSyncPendingMessage | ViewErrorMessage;
  if (diagnostic.severity === "warning") {
    message = { ...identity, type: "marimo-studio:view-sync-pending" };
  } else {
    const error: ViewErrorMessage = {
      ...identity,
      type: "marimo-studio:view-error",
      revision: view.revision,
      sessionId: view.sessionId ?? null,
    };
    message = error;
  }
  postToStudioParent(message);
};

const publishReady = (): void => {
  const view = renderedViewIdentity();
  const ready = {
    type: "marimo-studio:view-ready",
    runtime: view.runtime,
    ...documentLifecycleEnvelope(),
    view: view.view,
    revision: view.revision,
  } satisfies ViewReadyMessage;
  const message = view.sessionId === undefined ? ready : { ...ready, sessionId: view.sessionId };
  postToStudioParent(message);
};

const publishCommittedViewError = (): void => {
  const diagnostic = renderedViewDiagnostics().find(({ severity }) => severity === "error");
  if (!diagnostic) {
    return;
  }
  const view = renderedViewIdentity();
  const message: ViewErrorMessage = {
    type: "marimo-studio:view-error",
    runtime: view.runtime,
    ...documentLifecycleEnvelope(),
    diagnostic: toBrowserDiagnostic(diagnostic),
    revision: view.revision,
    sessionId: view.sessionId ?? null,
    view: view.view,
  };
  postToStudioParent(message);
};

const publish = (snapshot: ReadinessSnapshot, previous: ReadinessSnapshot): void => {
  document.documentElement.dataset.marimoStudioState = snapshot.page;
  publishRuntimeDiagnostic(snapshot.runtimeDiagnostic);
  if (snapshot.settled && !previous.settled) {
    document.dispatchEvent(
      new CustomEvent("marimo-studio:idle", { detail: { state: snapshot.page } }),
    );
  }
  if (snapshot.page === "ready" && previous.page !== "ready") {
    publishReady();
  }
  if (
    snapshot.page === "error" &&
    previous.page !== "error" &&
    snapshot.runtimeDiagnostic === undefined &&
    snapshot.presentationDiagnostic === undefined
  ) {
    publishCommittedViewError();
  }
};

const evaluate = (): void => {
  readiness.setHosts([...projectionHosts.states(), ...(viewStyleDiagnostic() ? ["error"] : [])]);
};

export const refreshRenderedView = (): void => {
  evaluate();
};

export const announceRenderedViewReady = (): void => {
  if (readiness.snapshot().page === "ready") {
    publishReady();
  }
};

const notifyRenderedViewChanged = (): void => {
  const activeGeneration = generation;
  if (pendingEvaluation === activeGeneration) {
    return;
  }
  pendingEvaluation = activeGeneration;
  queueMicrotask(() => {
    if (pendingEvaluation !== activeGeneration) {
      return;
    }
    pendingEvaluation = undefined;
    if (activeGeneration !== generation) {
      return;
    }
    evaluate();
  });
};

export const setRuntimeConnectionState = (
  state: RuntimeConnectionState,
  diagnostic?: Pick<RuntimeDiagnostic, "code" | "hint" | "message">,
): void => {
  const previous = readiness.snapshot().connection;
  readiness.setRuntime(
    state,
    diagnostic
      ? {
          ...diagnostic,
          scope: "runtime",
          severity: state === "error" ? "error" : "warning",
          view: renderedViewIdentity().view,
        }
      : undefined,
  );
  if (state === "ready" && previous !== "ready") {
    document.dispatchEvent(new CustomEvent("marimo-studio:runtime-ready"));
  }
};

export const startRenderedViewObserver = (updateQuery: (query: string) => Promise<void>): void => {
  stopRenderedViewObserver();
  readiness.start();
  document.documentElement.dataset.marimoStudioState = "connecting";
  globalThis.marimoStudio = {
    ready: () => {
      evaluate();
      return readiness.ready();
    },
    diagnostics: renderedViewDiagnostics,
    identity: () => {
      const config = getRuntimeConfig();
      return {
        projectionRevision: config.projectionRevision,
        revision: config.revision,
      };
    },
    projections: renderedProjectionInstances,
    updateQuery,
  };
  stopReadinessChanges = readiness.subscribe(publish);
  stopProjectionChanges = projectionHosts.subscribe(notifyRenderedViewChanged);
  observer = new MutationObserver(notifyRenderedViewChanged);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-state", "mo-value", "name", "value"],
    childList: true,
    subtree: true,
  });
  evaluate();
};

export const stopRenderedViewObserver = (): void => {
  generation += 1;
  pendingEvaluation = undefined;
  observer?.disconnect();
  observer = undefined;
  stopProjectionChanges?.();
  stopProjectionChanges = undefined;
  stopReadinessChanges?.();
  stopReadinessChanges = undefined;
};

declare global {
  var marimoStudio: MarimoStudioApi;
  interface Window {
    marimoStudio: MarimoStudioApi;
  }
}
