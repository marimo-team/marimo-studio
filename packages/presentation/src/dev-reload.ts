import type { ShellChangeKind } from "@marimo-studio/protocol/development-events";
import type { ReceiverReadyMessage } from "@marimo-studio/protocol/preview-messages";

import type { PresentationDiagnostic } from "./diagnostics.ts";

import { bindViewNavigation, bindViewSwitches, DevelopmentEvents } from "./document/events.ts";
import { PresentationDocument } from "./document/presentation.ts";
import {
  BaselineReconciler,
  RefreshRetrySchedule,
  ShellChangeQueue,
  ShellRefreshState,
  type ShellTarget,
} from "./document/refresh-state.ts";
import {
  clearDiagnostic,
  notifyDiagnostics,
  showDiagnostic,
  supportView,
} from "./document/status.ts";
import { isAbortError, StylesheetRefreshError } from "./document/styles.ts";
import { errorMessage } from "./errors.ts";
import { beginPresentationRefresh, setPresentationRefreshState } from "./readiness.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getMountConfig,
  getRuntimeConfig,
  getSupportUrl,
  hasRuntimeConfig,
  requestedRuntimeId,
  RuntimeConfigRequestError,
  subscribeRuntimeConfig,
} from "./runtime-config/index.ts";
import { updateConfiguredRuntime } from "./runtime/coordinator.ts";

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
  var __MARIMO_STUDIO_RUNTIME_STATE__: "booting" | "failed" | "mounted" | undefined;
}

const presentationDocument = new PresentationDocument();

export const refreshStylesheets = async (): Promise<void> => {
  await presentationDocument.refreshStylesheets();
};
const developmentEvents = new DevelopmentEvents();
let activeTransition: AbortController | undefined;
let activeConfigRefresh: AbortController | undefined;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
const retrySchedule = new RefreshRetrySchedule();
let latestRefreshGeneration = 0;
const shellRefreshState = new ShellRefreshState();
const shellChangeQueue = new ShellChangeQueue();
const baselineReconciler = new BaselineReconciler(hasRuntimeConfig());

const REFRESH_FAILURE_CODES: Record<ShellChangeKind, string> = {
  css: "stylesheet-refresh-failed",
  html: "shell-refresh-failed",
  runtime: "runtime-config-refresh-failed",
  views: "shell-refresh-failed",
};

const queueChange = (kind: ShellChangeKind) => {
  shellChangeQueue.push(kind);
};

const cancelRetry = () => {
  if (retryTimer !== undefined) {
    clearTimeout(retryTimer);
    retryTimer = undefined;
  }
};

const resetRetry = () => {
  cancelRetry();
  retrySchedule.reset();
};

const scheduleRetry = (kind: ShellChangeKind) => {
  cancelRetry();
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    reload(kind, false);
  }, retrySchedule.next());
};

const refreshFailureCode = (error: unknown, kind: ShellChangeKind): string => {
  if (error instanceof RuntimeConfigRequestError || error instanceof StylesheetRefreshError) {
    return error.code;
  }
  return REFRESH_FAILURE_CODES[kind];
};

const refreshFailureHint = (error: unknown, transient: boolean): string => {
  if (error instanceof RuntimeConfigRequestError && error.hint) {
    return error.hint;
  }
  return transient
    ? "Wait for Marimo to accept the notebook change."
    : "Fix the view source, then save it again.";
};

const refreshDiagnostic = (
  error: unknown,
  kind: ShellChangeKind,
  view = supportView(),
): PresentationDiagnostic => {
  const transient = error instanceof RuntimeConfigRequestError && error.transient;
  return {
    scope: "presentation",
    code: refreshFailureCode(error, kind),
    severity: transient ? "warning" : "error",
    message: errorMessage(error),
    hint: refreshFailureHint(error, transient),
    view: view ?? "",
  };
};

const handleRefreshError = (
  error: unknown,
  kind: ShellChangeKind,
  generation: number,
  view = supportView(),
) => {
  if (isAbortError(error) || generation !== latestRefreshGeneration) {
    return;
  }
  const diagnostic = refreshDiagnostic(error, kind, view);
  if (error instanceof RuntimeConfigRequestError && error.transient) {
    showDiagnostic(diagnostic, "waiting");
    setPresentationRefreshState(generation, "loading", diagnostic);
    scheduleRetry(kind);
    return;
  }
  resetRetry();
  showDiagnostic(diagnostic);
  setPresentationRefreshState(generation, "error", diagnostic);
};

const refreshRuntimeConfig = async (): Promise<void> => {
  activeConfigRefresh?.abort();
  const controller = new AbortController();
  activeConfigRefresh = controller;
  try {
    const config = commitRuntimeConfig(
      await fetchRuntimeConfig(
        getSupportUrl(),
        controller.signal,
        hasRuntimeConfig() ? getRuntimeConfig().runtime.id : requestedRuntimeId(),
      ),
    );
    if (updateConfiguredRuntime(config) === "reload") {
      globalThis.location.reload();
    }
    clearDiagnostic();
  } finally {
    if (activeConfigRefresh === controller) {
      activeConfigRefresh = undefined;
    }
  }
};

const beginRefresh = (): number => {
  latestRefreshGeneration = beginPresentationRefresh();
  return latestRefreshGeneration;
};

const completeRefresh = (generation: number) => {
  if (generation !== latestRefreshGeneration) {
    return;
  }
  resetRetry();
  clearDiagnostic();
  setPresentationRefreshState(generation, "ready");
};

const reload = (kind: ShellChangeKind, resetBackoff = true) => {
  if (kind === "views" && !shellRefreshState.pending) {
    return;
  }
  if (resetBackoff) {
    resetRetry();
  } else {
    cancelRetry();
  }
  if (activeTransition) {
    queueChange(kind);
    return;
  }
  if (kind === "css" && !shellRefreshState.pending) {
    activeConfigRefresh?.abort();
    const generation = beginRefresh();
    void refreshStylesheets()
      .then(() => completeRefresh(generation))
      .catch((error: unknown) => {
        handleRefreshError(error, kind, generation);
      });
    return;
  }
  if (kind === "runtime" && !shellRefreshState.pending) {
    presentationDocument.abortStyles();
    const generation = beginRefresh();
    void refreshRuntimeConfig()
      .then(() => completeRefresh(generation))
      .catch((error: unknown) => {
        handleRefreshError(error, kind, generation);
      });
    return;
  }
  const target = shellRefreshState.targetForChange(kind, {
    documentUrl: presentationDocument.url,
    supportUrl: getSupportUrl(),
  });
  if (!target) {
    return;
  }
  const generation = beginRefresh();
  void refreshShell(target.documentUrl, target.supportUrl)
    .then(() => completeRefresh(generation))
    .catch((error: unknown) => {
      const failed = shellRefreshState.failedTarget ?? target;
      handleRefreshError(error, kind, generation, supportView(failed.supportUrl));
    });
};

const reconcileBaseline = () => {
  if (baselineReconciler.ready()) {
    reload("html");
  }
};

subscribeRuntimeConfig(() => {
  notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
  if (baselineReconciler.configure()) {
    reload("html");
  }
});

if (hasRuntimeConfig()) {
  notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
}

const connectEvents = () => {
  developmentEvents.connect(`${getSupportUrl()}/dev/events`, reconcileBaseline, (kind) => {
    if (globalThis.__MARIMO_STUDIO_RUNTIME_STATE__ === "failed") {
      globalThis.location.reload();
      return;
    }
    reload(kind);
  });
};

export const refreshShell = async (
  nextDocumentUrl = presentationDocument.url,
  nextSupportUrl = getSupportUrl(),
) => {
  let target: ShellTarget = {
    documentUrl: nextDocumentUrl,
    supportUrl: nextSupportUrl,
  };
  presentationDocument.abortStyles();
  activeConfigRefresh?.abort();
  activeTransition?.abort();
  const controller = new AbortController();
  activeTransition = controller;
  try {
    const commit = await presentationDocument.replace(
      nextDocumentUrl,
      nextSupportUrl,
      controller.signal,
      (resolvedTarget) => {
        target = resolvedTarget;
      },
    );
    if (updateConfiguredRuntime(getRuntimeConfig()) === "reload") {
      globalThis.location.reload();
      return;
    }
    clearDiagnostic();
    if (commit.supportChanged) {
      connectEvents();
    }
    shellRefreshState.complete(commit.target);
  } catch (error) {
    if (!isAbortError(error)) {
      shellRefreshState.rememberFailure(target);
    }
    throw error;
  } finally {
    if (activeTransition === controller) {
      activeTransition = undefined;
      const queued = shellChangeQueue.take();
      if (queued) {
        queueMicrotask(() => reload(queued));
      }
    }
  }
};

const transitionToView = (documentUrl: string, supportUrl: string, view: string) => {
  resetRetry();
  shellRefreshState.supersede();
  const generation = beginRefresh();
  void refreshShell(documentUrl, supportUrl)
    .then(() => completeRefresh(generation))
    .catch((error: unknown) => {
      handleRefreshError(error, "html", generation, view);
    });
};

const unbindViewSwitches = bindViewSwitches((request) => {
  transitionToView(request.documentUrl, request.supportUrl, request.view);
});
const unbindViewNavigation = bindViewNavigation((request) => {
  transitionToView(request.documentUrl, getSupportUrl(), request.view);
});

connectEvents();
const receiverReady: ReceiverReadyMessage = {
  type: "marimo-studio:receiver-ready",
  runtime: hasRuntimeConfig()
    ? getRuntimeConfig().runtime.id
    : requestedRuntimeId(getMountConfig().runtime),
  view: supportView(),
};
globalThis.parent.postMessage(receiverReady, globalThis.location.origin);
globalThis.addEventListener(
  "pagehide",
  () => {
    resetRetry();
    presentationDocument.abortStyles();
    activeConfigRefresh?.abort();
    activeTransition?.abort();
    developmentEvents.close();
    unbindViewSwitches();
    unbindViewNavigation();
  },
  { once: true },
);
