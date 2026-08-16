import type {
  ObserveViewMessage,
  ViewObservationMessage,
} from "@marimo-studio/protocol/preview-messages";

import { parsePreviewMessage } from "@marimo-studio/protocol/preview-messages";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import type { ReadinessSnapshot } from "./readiness.ts";

import { messageJson } from "./json.ts";
import { toBrowserDiagnostics } from "./readiness-diagnostics.ts";
import { readiness } from "./readiness.ts";
import { refreshRenderedView } from "./rendered-view-observer.ts";
import { renderedViewDiagnostics, renderedViewIdentity } from "./rendered-view-state.ts";

type BrowserObservationState = "loading" | "ready" | "error";

let pending: { request: ObserveViewMessage; state?: BrowserObservationState } | undefined;
let stopReadiness: (() => void) | undefined;

const observationState = (snapshot: ReadinessSnapshot): BrowserObservationState =>
  snapshot.settled && snapshot.page !== "connecting" ? snapshot.page : "loading";

const publishObservation = (request: ObserveViewMessage, state: BrowserObservationState): void => {
  const view = renderedViewIdentity();
  const message: ViewObservationMessage = {
    type: "marimo-studio:view-observation",
    runtime: view.runtime,
    view: view.view,
    revision: view.revision,
    state,
    diagnostics: toBrowserDiagnostics(renderedViewDiagnostics()),
    runtimeInstance: view.runtimeInstance ?? request.runtimeInstance,
    sessionId: view.sessionId ?? null,
    requestId: request.requestId,
    query: publicNotebookQuery(globalThis.location.search),
  };
  globalThis.parent.postMessage(message, globalThis.location.origin);
};

const publish = (snapshot: ReadinessSnapshot): void => {
  if (!pending) {
    return;
  }
  const view = renderedViewIdentity();
  const request = pending.request;
  const state = observationState(snapshot);
  if (
    request.runtime !== view.runtime ||
    request.view !== view.view ||
    request.revision !== view.revision ||
    (view.runtimeInstance !== undefined && request.runtimeInstance !== view.runtimeInstance) ||
    pending.state === state
  ) {
    return;
  }
  publishObservation(request, state);
  pending.state = state;
  if (snapshot.settled) {
    pending = undefined;
  }
};

const observationRequested = (event: MessageEvent<unknown>): void => {
  if (event.origin !== globalThis.location.origin || event.source !== globalThis.parent) {
    return;
  }
  const payload = messageJson(event);
  if (payload === undefined) {
    return;
  }
  const request = parsePreviewMessage(payload);
  if (request?.type !== "marimo-studio:observe-view") {
    return;
  }
  pending = { request };
  refreshRenderedView();
  publish(readiness.snapshot());
};

export const startAgentObserver = (): void => {
  stopAgentObserver();
  stopReadiness = readiness.subscribe(publish);
  globalThis.addEventListener("message", observationRequested);
};

export const stopAgentObserver = (): void => {
  stopReadiness?.();
  stopReadiness = undefined;
  pending = undefined;
  globalThis.removeEventListener("message", observationRequested);
};
