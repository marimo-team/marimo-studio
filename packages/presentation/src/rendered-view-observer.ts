import type {
  ViewErrorMessage,
  ViewReadyMessage,
  ViewSyncPendingMessage,
} from "@marimo-studio/protocol/preview-messages";

import type { RuntimeDiagnostic, StudioDiagnostic } from "./diagnostics.ts";

import { projectionHosts } from "./projections/host-runtime.ts";
import { type ReadinessSnapshot, readiness, type RuntimeConnectionState } from "./readiness.ts";
import { renderedViewDiagnostics, renderedViewIdentity } from "./rendered-view-state.ts";

interface MarimoStudioApi {
  ready: () => Promise<void>;
  diagnostics: () => readonly StudioDiagnostic[];
  updateQuery: (query: string) => Promise<void>;
}

let observer: MutationObserver | undefined;
let stopProjectionChanges: (() => void) | undefined;
let stopReadinessChanges: (() => void) | undefined;
let generation = 0;

const runtimeDiagnosticHost = (): HTMLElement => {
  const existing = document.querySelector<HTMLElement>("[data-marimo-studio-runtime-diagnostic]");
  if (existing) {
    return existing;
  }
  const host = document.createElement("div");
  host.dataset.marimoStudioRuntimeDiagnostic = "";
  host.setAttribute("role", "alert");
  host.hidden = true;
  document.body.append(host);
  return host;
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
  host.hidden = diagnostic.severity === "warning" && globalThis.parent !== globalThis.window;
  const view = renderedViewIdentity();
  const message: ViewSyncPendingMessage | ViewErrorMessage = {
    type:
      diagnostic.severity === "warning"
        ? "marimo-studio:view-sync-pending"
        : "marimo-studio:view-error",
    runtime: view.runtime,
    message: diagnostic.message,
    hint: diagnostic.hint,
    view: diagnostic.view,
  };
  globalThis.parent.postMessage(message, globalThis.location.origin);
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
    const view = renderedViewIdentity();
    const message: ViewReadyMessage = {
      type: "marimo-studio:view-ready",
      runtime: view.runtime,
      view: view.view,
      revision: view.revision,
      sessionId: view.sessionId,
    };
    globalThis.parent.postMessage(message, globalThis.location.origin);
  }
};

const evaluate = (): void => {
  const presentationStates = Array.from(
    document.querySelectorAll<HTMLElement>('[data-marimo-diagnostic-scope="presentation"]'),
    (host) => host.dataset.state ?? "connecting",
  );
  readiness.setHosts([...projectionHosts.states(), ...presentationStates]);
};

export const refreshRenderedView = (): void => {
  evaluate();
};

const notifyRenderedViewChanged = (): void => {
  const activeGeneration = generation;
  queueMicrotask(() => {
    if (activeGeneration === generation) {
      evaluate();
    }
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
