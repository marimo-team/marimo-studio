import type {
  NavigateViewMessage,
  ReceiverReadyMessage,
  ReceiverUnreadyMessage,
} from "@marimo-studio/protocol/preview-messages";

import {
  beginProjectedOutputFunctionTransition,
  cancelProjectedOutputFunctionTransition,
  completeProjectedOutputFunctionTransition,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";
import {
  presentationBuildNotice,
  type PresentationBuild,
} from "@marimo-studio/protocol/development-events";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type {
  PresentationRevisionController,
  PresentationRevisionPolicy,
} from "./document/revision-controller.ts";

import { DevelopmentViewTransition } from "./document/development-view-transition.ts";
import { documentLifecycleEnvelope } from "./document/document-lifecycle-id.ts";
import {
  bindPresentationEvents,
  bindViewNavigation,
  bindViewSwitches,
  DevelopmentEvents,
} from "./document/events.ts";
import { ExternalRefreshGate } from "./document/external-refresh-gate.ts";
import { coordinatePresentationMutationBarrier } from "./document/mutation-barrier.ts";
import { bindDocumentPresence } from "./document/page-lifecycle.ts";
import { postToStudioParent } from "./document/parent-bridge.ts";
import {
  BaselineReconciler,
  RefreshRetrySchedule,
  PresentationRefreshState,
  refreshDiagnostic,
  StaleBindingRefresh,
} from "./document/presentation-refresh.ts";
import { ReceiverRefreshHandshake } from "./document/receiver-refresh.ts";
import { presentationRenewalSupportUrl } from "./document/refresh-url.ts";
import { waitForPresentationRevisions } from "./document/revision-runtime.ts";
import {
  clearDiagnostic,
  notifyDiagnostics,
  showDiagnostic,
  supportView,
} from "./document/status.ts";
import { studioOwned } from "./document/studio-ownership.ts";
import { projectionReadGate } from "./projections/read-gate.ts";
import { bindProjectionBindingStale, projectionBindingIsStale } from "./projections/staleness.ts";
import {
  beginPresentationRefresh,
  setPresentationRefreshState,
  readiness,
  type PresentationRefreshClaim,
} from "./readiness.ts";
import { announceRenderedViewReady } from "./rendered-view-observer.ts";
import {
  getMountConfig,
  getRuntimeConfig,
  getSupportUrl,
  hasRuntimeConfig,
  subscribeRuntimeConfig,
} from "./runtime-config/index.ts";

declare global {
  var __MARIMO_STUDIO_RUNTIME_STATE__: "booting" | "failed" | "mounted" | undefined;
}

const developmentEvents = new DevelopmentEvents();
const retrySchedule = new RefreshRetrySchedule();
const presentationRefreshState = new PresentationRefreshState();
const staleBindingRefresh = new StaleBindingRefresh();
const ownedByStudio = studioOwned();
let baselineReconciler: BaselineReconciler;
let presentationRevisions: PresentationRevisionController;
let viewTransitions: DevelopmentViewTransition;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let announcedReceiverRevision: string | undefined;
let buildClaim: PresentationRefreshClaim | undefined;
let pendingBuildRevision: string | undefined;
let developmentClaim: PresentationRefreshClaim | undefined;
const externalRefreshGate = new ExternalRefreshGate(projectionReadGate, {
  begin: beginProjectedOutputFunctionTransition,
  cancel: cancelProjectedOutputFunctionTransition,
  complete: completeProjectedOutputFunctionTransition,
});

const cancelRetry = (): void => {
  if (retryTimer !== undefined) {
    clearTimeout(retryTimer);
    retryTimer = undefined;
  }
};

const resetRetry = (): void => {
  cancelRetry();
  retrySchedule.reset();
};

const scheduleRetry = (): void => {
  cancelRetry();
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    reload(false);
  }, retrySchedule.next());
};

const observeBuild = (build: PresentationBuild): void => {
  if (build.phase === "building") {
    buildClaim = beginPresentationRefresh("build");
    pendingBuildRevision = undefined;
    externalRefreshGate.refresh("pending");
    return;
  }
  buildClaim ??= beginPresentationRefresh("build");
  const notice = presentationBuildNotice(build, supportView());
  if (notice) {
    externalRefreshGate.refresh("settled");
    // The previous build stays on screen and usable, so the failure is a notice.
    setPresentationRefreshState(buildClaim, "ready", notice);
    console.error("marimo-studio build error", notice.message);
    return;
  }
  if (build.revision !== null) {
    pendingBuildRevision = build.revision;
    settleBuild();
  }
};

const settleBuild = (): void => {
  if (buildClaim && pendingBuildRevision === getRuntimeConfig().revision) {
    setPresentationRefreshState(buildClaim, "ready");
    buildClaim = undefined;
    pendingBuildRevision = undefined;
    externalRefreshGate.refresh("settled");
  }
};

const connectEvents = (): void => {
  const supportUrl = presentationRenewalSupportUrl(presentationRevisions.url, getSupportUrl());
  const eventsUrl = appendUrlPath(supportUrl, "dev/events");
  developmentEvents.connect(
    eventsUrl,
    reconcileBaseline,
    () => {
      if (globalThis.__MARIMO_STUDIO_RUNTIME_STATE__ === "failed") {
        externalRefreshGate.cancel();
        globalThis.location.reload();
        return;
      }
      presentationChanged();
    },
    observeBuild,
    () => {
      developmentClaim ??= beginPresentationRefresh("development");
      setPresentationRefreshState(developmentClaim, "loading", {
        scope: "presentation",
        severity: "warning",
        code: "development-disconnected",
        message: "Live updates disconnected. Reconnecting…",
        hint: "Check that the Studio server is available.",
        view: supportView(),
      });
    },
    (wasReady) => {
      if (wasReady && !ownedByStudio) {
        void recoverRejectedStream(eventsUrl);
        return;
      }
      developmentClaim ??= beginPresentationRefresh("development");
      setPresentationRefreshState(developmentClaim, "error", {
        scope: "presentation",
        severity: "error",
        code: "development-rejected",
        message: "Live updates stopped because the server no longer accepts this page.",
        hint: "Reload the page to reconnect.",
        view: supportView(),
      });
    },
  );
};

// A rejected stream URL distinguishes a restarted server from a proxy that
// answers while the server is away. Studio rejects a capability from an
// earlier process with a readable 403. A proxy error carries no CORS grant.
const probeStream = async (url: string): Promise<"accepted" | "rejected" | "unavailable"> => {
  const request = new AbortController();
  try {
    const response = await fetch(url, { cache: "no-store", signal: request.signal });
    if (response.ok) {
      return "accepted";
    }
    return response.status === 403 ? "rejected" : "unavailable";
  } catch {
    return "unavailable";
  } finally {
    request.abort();
  }
};

// The public view address assigns a fresh presentation session after a
// restart, so a standalone page reloads it.
const recoverRejectedStream = async (url: string): Promise<void> => {
  developmentClaim ??= beginPresentationRefresh("development");
  setPresentationRefreshState(developmentClaim, "loading", {
    scope: "presentation",
    severity: "warning",
    code: "development-disconnected",
    message: "Live updates disconnected. Reconnecting…",
    hint: "Check that the Studio server is available.",
    view: supportView(),
  });
  const schedule = new RefreshRetrySchedule();
  let probe = await probeStream(url);
  while (probe === "unavailable") {
    await new Promise((resume) => setTimeout(resume, schedule.next()));
    probe = await probeStream(url);
  }
  if (probe === "accepted") {
    connectEvents();
    return;
  }
  externalRefreshGate.cancel();
  if (globalThis.parent === globalThis.window) {
    globalThis.location.reload();
    return;
  }
  const config = getRuntimeConfig();
  const message: NavigateViewMessage = {
    type: "marimo-studio:navigate-view",
    runtime: config.runtime.id,
    ...documentLifecycleEnvelope(),
    view: config.view,
    query: globalThis.location.search,
    hash: globalThis.location.hash,
  };
  postToStudioParent(message);
};

const presentationChanged = (): void => {
  if (ownedByStudio) {
    receiverRefreshHandshake.begin();
  }
  externalRefreshGate.presentationChanged();
  reload();
};

const revisionPolicy: PresentationRevisionPolicy = {
  classifyFailure: (error, operation) => {
    const diagnostic = refreshDiagnostic(error, supportView(operation.target.supportUrl) ?? "");
    return {
      state: diagnostic.severity === "warning" ? "loading" : "error",
      diagnostic,
    };
  },
  onFailure: (error, operation, failure) => {
    presentationRefreshState.rememberFailure(operation.target);
    if (failure.state === "loading") {
      showDiagnostic(failure.diagnostic, "waiting");
      scheduleRetry();
      return;
    }
    resetRetry();
    receiverRefreshHandshake.fail();
    showDiagnostic(failure.diagnostic);
    console.error("marimo-studio presentation refresh error", error);
  },
  onReady: (operation) => {
    const { presentationDiagnostic, presentationNotice } = readiness.snapshot();
    if (!presentationDiagnostic && !presentationNotice) {
      clearDiagnostic();
    }
    presentationRefreshState.complete(operation.target);
    if (hasRuntimeConfig()) {
      const projectionRevision = getRuntimeConfig().projectionRevision;
      if (!projectionBindingIsStale(projectionRevision)) {
        staleBindingRefresh.clear();
      }
    }
    if (
      hasRuntimeConfig() &&
      staleBindingRefresh.needsRetry(getRuntimeConfig().projectionRevision)
    ) {
      scheduleRetry();
      return;
    }
    resetRetry();
    if (ownedByStudio) {
      receiverRefreshHandshake.complete();
    }
  },
  onSupportChanged: () => {
    if (!ownedByStudio) {
      connectEvents();
    }
  },
};

const reload = (resetBackoff = true): void => {
  if (resetBackoff) {
    resetRetry();
  } else {
    cancelRetry();
  }
  const target = presentationRefreshState.failedTarget ?? {
    documentUrl: presentationRevisions.url,
    supportUrl: getSupportUrl(),
  };
  void presentationRevisions
    .transition(target.documentUrl, target.supportUrl, "presentation", revisionPolicy)
    .catch(() => {});
};

function reconcileBaseline(revision?: string | null): void {
  const reconnecting = developmentClaim !== undefined;
  if (developmentClaim) {
    setPresentationRefreshState(developmentClaim, "ready");
    developmentClaim = undefined;
  }
  if (
    baselineReconciler.ready(
      reconnecting || (revision !== undefined && revision !== getRuntimeConfig().revision),
    )
  ) {
    reload();
  }
}

const transitionToView = (documentUrl: string, supportUrl: string): void => {
  resetRetry();
  presentationRefreshState.supersede();
  void viewTransitions.run(documentUrl, supportUrl);
};

const announceReceiver = (force = false): void => {
  const config = getRuntimeConfig();
  if (!force && announcedReceiverRevision === config.revision) {
    return;
  }
  announcedReceiverRevision = config.revision;
  const receiverReady: ReceiverReadyMessage = {
    runtime: config.runtime.id,
    view: supportView(),
    ...documentLifecycleEnvelope(),
    type: "marimo-studio:receiver-ready",
    revision: config.revision,
  };
  postToStudioParent(receiverReady);
};

const receiverIdentity = () => ({
  runtime: hasRuntimeConfig() ? getRuntimeConfig().runtime.id : getMountConfig().runtime,
  view: supportView(),
});

const announceReceiverUnready = (): void => {
  const receiverUnready: ReceiverUnreadyMessage = {
    ...receiverIdentity(),
    ...documentLifecycleEnvelope(),
    type: "marimo-studio:receiver-unready",
  };
  postToStudioParent(receiverUnready);
};

const receiverRefreshHandshake = new ReceiverRefreshHandshake({
  unready: announceReceiverUnready,
  ready: () => announceReceiver(true),
  viewReady: announceRenderedViewReady,
});

const startDevelopmentReload = async (): Promise<void> => {
  presentationRevisions = await waitForPresentationRevisions();
  baselineReconciler = new BaselineReconciler(hasRuntimeConfig());
  viewTransitions = new DevelopmentViewTransition({
    embedded: ownedByStudio,
    closeEvents: () => developmentEvents.close(),
    connectEvents,
    replaceView: (documentUrl, supportUrl) =>
      presentationRevisions.transition(documentUrl, supportUrl, "view", revisionPolicy),
  });
  subscribeRuntimeConfig(() => {
    settleBuild();
    notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
    if (baselineReconciler.configure()) {
      reload();
    }
  });
  if (hasRuntimeConfig()) {
    notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
  }
  const unbindViewSwitches = bindViewSwitches((request) => {
    transitionToView(request.documentUrl, request.supportUrl);
  });
  const unbindViewNavigation = bindViewNavigation((request) => {
    globalThis.location.assign(request.documentUrl);
    return false;
  });
  const unbindPresentationEvents = bindPresentationEvents({
    changed: presentationChanged,
    refresh: (phase, diagnostic) => {
      externalRefreshGate.refresh(phase);
      if (phase === "pending") {
        buildClaim = beginPresentationRefresh("build");
      } else if (buildClaim || diagnostic) {
        buildClaim ??= beginPresentationRefresh("build");
        setPresentationRefreshState(
          buildClaim,
          "ready",
          diagnostic ? { ...diagnostic, scope: "presentation" } : undefined,
        );
        if (!diagnostic) {
          buildClaim = undefined;
        }
      }
    },
    barrier: (port, generation, signal, result) => {
      const lease = externalRefreshGate.acquire("mutation");
      void coordinatePresentationMutationBarrier({
        drained: lease.drained,
        generation,
        onFailure: () => lease.release(),
        port,
        result,
        signal,
      });
    },
  });
  const unbindProjectionBindingStale = bindProjectionBindingStale(() => {
    if (
      !hasRuntimeConfig() ||
      !staleBindingRefresh.request(getRuntimeConfig().projectionRevision)
    ) {
      return;
    }
    reload();
  });
  if (!ownedByStudio) {
    connectEvents();
  }
  bindDocumentPresence({
    ready: () => {
      if (!receiverRefreshHandshake.active) {
        announceReceiver(true);
        announceRenderedViewReady();
      }
    },
    unready: announceReceiverUnready,
    dispose: () => {
      viewTransitions.cancel();
      staleBindingRefresh.clear();
      resetRetry();
      presentationRevisions.dispose();
      developmentEvents.close();
      unbindProjectionBindingStale();
      externalRefreshGate.cancel();
      receiverRefreshHandshake.release();
      unbindPresentationEvents();
      unbindViewSwitches();
      unbindViewNavigation();
    },
  });
};

void startDevelopmentReload();
