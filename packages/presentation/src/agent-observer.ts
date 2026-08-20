import type {
  ObserveViewMessage,
  ViewObservationMessage,
} from "@marimo-studio/protocol/preview-messages";

import { parsePreviewMessage } from "@marimo-studio/protocol/preview-messages";
import {
  type ObservedProjectionInstance,
  projectionInstanceIsReady,
} from "@marimo-studio/protocol/projections";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import type { ReadinessSnapshot } from "./readiness.ts";

import {
  activeDocumentLifecycleId,
  documentLifecycleEnvelope,
} from "./document/document-lifecycle-id.ts";
import { isStudioParentMessage, postToStudioParent } from "./document/parent-bridge.ts";
import { renderedProjectionInstances } from "./projections/instances.ts";
import { toBrowserDiagnostics } from "./readiness-diagnostics.ts";
import { readiness } from "./readiness.ts";
import { refreshRenderedView } from "./rendered-view-observer.ts";
import { renderedViewDiagnostics, renderedViewIdentity } from "./rendered-view-state.ts";
import { subscribeRuntimeConfig } from "./runtime-config/index.ts";

type BrowserObservationState = "loading" | "ready" | "error";

let pending: { request: ObserveViewMessage; state?: BrowserObservationState } | undefined;
let stopConfig: (() => void) | undefined;
let stopReadiness: (() => void) | undefined;

const observationState = (
  snapshot: ReadinessSnapshot,
  instances: readonly ObservedProjectionInstance[],
): BrowserObservationState => {
  const page = snapshot.settled && snapshot.page !== "connecting" ? snapshot.page : "loading";
  if (page !== "ready") {
    return page;
  }
  return instances.every(projectionInstanceIsReady) ? "ready" : "loading";
};

const publishObservation = (
  request: ObserveViewMessage,
  state: BrowserObservationState,
  projectionInstances: readonly ObservedProjectionInstance[],
): void => {
  const view = renderedViewIdentity();
  const message: ViewObservationMessage = {
    type: "marimo-studio:view-observation",
    runtime: view.runtime,
    ...documentLifecycleEnvelope(),
    view: view.view,
    revision: view.revision,
    state,
    diagnostics: toBrowserDiagnostics(renderedViewDiagnostics()),
    runtimeInstance: view.runtimeInstance ?? request.runtimeInstance,
    sessionId: view.sessionId ?? null,
    requestId: request.requestId,
    query: publicNotebookQuery(globalThis.location.search),
    projectionInstances: [...projectionInstances],
  };
  postToStudioParent(message);
};

const publish = (snapshot: ReadinessSnapshot): void => {
  if (!pending) {
    return;
  }
  const view = renderedViewIdentity();
  const request = pending.request;
  const projectionInstances = renderedProjectionInstances();
  const state = observationState(snapshot, projectionInstances);
  if (
    request.runtime !== view.runtime ||
    request.view !== view.view ||
    request.revision !== view.revision ||
    (view.runtimeInstance !== undefined && request.runtimeInstance !== view.runtimeInstance) ||
    pending.state === state
  ) {
    return;
  }
  publishObservation(request, state, projectionInstances);
  pending.state = state;
  if (state !== "loading") {
    pending = undefined;
  }
};

const observationRequested = (event: MessageEvent<unknown>): void => {
  if (!isStudioParentMessage(event)) {
    return;
  }
  const request = parsePreviewMessage(event.data);
  if (
    request?.type !== "marimo-studio:observe-view" ||
    request.lifecycleId !== activeDocumentLifecycleId()
  ) {
    return;
  }
  pending = { request };
  refreshRenderedView();
  publish(readiness.snapshot());
};

export const startAgentObserver = (): void => {
  stopAgentObserver();
  stopReadiness = readiness.subscribe(publish);
  stopConfig = subscribeRuntimeConfig(() => publish(readiness.snapshot()));
  globalThis.addEventListener("message", observationRequested);
};

export const stopAgentObserver = (): void => {
  stopConfig?.();
  stopConfig = undefined;
  stopReadiness?.();
  stopReadiness = undefined;
  pending = undefined;
  globalThis.removeEventListener("message", observationRequested);
};
