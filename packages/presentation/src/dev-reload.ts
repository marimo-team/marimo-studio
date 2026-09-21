import type { PresentationBuild } from "@marimo-studio/protocol/development-events";
import type {
  ReceiverReadyMessage,
  ReceiverUnreadyMessage,
} from "@marimo-studio/protocol/preview-messages";

import {
  beginProjectedOutputFunctionTransition,
  cancelProjectedOutputFunctionTransition,
  completeProjectedOutputFunctionTransition,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { PresentationDiagnostic } from "./diagnostics.ts";
import type {
  PresentationRevisionController,
  PresentationRevisionPolicy,
  RevisionOperation,
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
  StaleBindingRefresh,
} from "./document/presentation-refresh.ts";
import { ReceiverRefreshHandshake } from "./document/receiver-refresh.ts";
import { waitForPresentationRevisions } from "./document/revision-runtime.ts";
import {
  clearDiagnostic,
  notifyDiagnostics,
  showDiagnostic,
  supportView,
} from "./document/status.ts";
import { studioOwned } from "./document/studio-ownership.ts";
import { StylesheetRefreshError } from "./document/styles.ts";
import { errorMessage } from "./errors.ts";
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
  RuntimeConfigRequestError,
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

const refreshFailureCode = (cause: unknown): string => {
  if (cause instanceof RuntimeConfigRequestError || cause instanceof StylesheetRefreshError) {
    return cause.code;
  }
  return "presentation-refresh-failed";
};

const refreshFailureHint = (cause: unknown, transient: boolean): string => {
  if (cause instanceof RuntimeConfigRequestError && cause.hint) {
    return cause.hint;
  }
  return transient
    ? "Wait for Marimo to accept the notebook change."
    : "Fix the view source, then save it again.";
};

const refreshDiagnostic = (
  cause: unknown,
  operation: RevisionOperation,
): PresentationDiagnostic => {
  const transient = cause instanceof RuntimeConfigRequestError && cause.transient;
  return {
    scope: "presentation",
    code: refreshFailureCode(cause),
    severity: transient ? "warning" : "error",
    message: errorMessage(cause),
    hint: refreshFailureHint(cause, transient),
    view: supportView(operation.target.supportUrl) ?? "",
    details: cause instanceof RuntimeConfigRequestError ? cause.details : undefined,
  };
};

const observeBuild = (build: PresentationBuild): void => {
  if (build.phase === "building") {
    buildClaim = beginPresentationRefresh("build");
    pendingBuildRevision = undefined;
    externalRefreshGate.refresh("pending");
    return;
  }
  buildClaim ??= beginPresentationRefresh("build");
  if (build.revision === null || build.build.phase === "failed") {
    externalRefreshGate.refresh("settled");
    const detail = build.build.diagnostics.find(({ severity }) => severity === "error");
    const diagnostic: PresentationDiagnostic = {
      scope: "presentation",
      code:
        detail?.code ??
        (build.build.phase === "failed" ? "view-build-failed" : "view-publication-unavailable"),
      severity: "error",
      message: `${build.build.phase === "failed" ? "Latest build failed." : "Latest publication is unavailable."} Showing the previous build.${detail ? ` ${detail.message}` : ""}`,
      hint: detail?.hint ?? "Fix the view source, then build it again.",
      source: detail?.source ?? undefined,
      view: supportView(),
    };
    setPresentationRefreshState(buildClaim, "error", diagnostic);
    console.error("marimo-studio build error", diagnostic.message);
    return;
  }
  pendingBuildRevision = build.revision;
  settleBuild();
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
  developmentEvents.connect(
    appendUrlPath(getSupportUrl(), "dev/events", globalThis.location.href),
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
  );
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
    const diagnostic = refreshDiagnostic(error, operation);
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
    showDiagnostic(failure.diagnostic);
    console.error("marimo-studio presentation refresh error", error);
  },
  onReady: (operation) => {
    if (!readiness.snapshot().presentationDiagnostic) {
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
          diagnostic ? "error" : "ready",
          diagnostic
            ? {
                ...diagnostic,
                scope: "presentation",
              }
            : undefined,
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
