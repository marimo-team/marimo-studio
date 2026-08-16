import type { ShellChangeKind } from "@marimo-studio/protocol/development-events";
import type { ReceiverReadyMessage } from "@marimo-studio/protocol/preview-messages";

import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { PresentationDiagnostic } from "./diagnostics.ts";
import type {
  PresentationRevisionController,
  PresentationRevisionPolicy,
  RevisionOperation,
} from "./document/revision-controller.ts";

import { bindViewNavigation, bindViewSwitches, DevelopmentEvents } from "./document/events.ts";
import {
  BaselineReconciler,
  RefreshRetrySchedule,
  ShellRefreshState,
} from "./document/refresh-state.ts";
import { waitForPresentationRevisions } from "./document/revision-runtime.ts";
import {
  clearDiagnostic,
  notifyDiagnostics,
  showDiagnostic,
  supportView,
} from "./document/status.ts";
import { StylesheetRefreshError } from "./document/styles.ts";
import { errorMessage } from "./errors.ts";
import {
  getMountConfig,
  getRuntimeConfig,
  getSupportUrl,
  hasRuntimeConfig,
  requestedRuntimeId,
  RuntimeConfigRequestError,
  subscribeRuntimeConfig,
} from "./runtime-config/index.ts";

declare global {
  var __MARIMO_STUDIO_RUNTIME_STATE__: "booting" | "failed" | "mounted" | undefined;
}

const developmentEvents = new DevelopmentEvents();
const retrySchedule = new RefreshRetrySchedule();
const shellRefreshState = new ShellRefreshState();
const baselineReconciler = new BaselineReconciler(hasRuntimeConfig());
let presentationRevisions: PresentationRevisionController;
let retryTimer: ReturnType<typeof setTimeout> | undefined;

const REFRESH_FAILURE_CODES = {
  css: "stylesheet-refresh-failed",
  html: "shell-refresh-failed",
  runtime: "runtime-config-refresh-failed",
  views: "shell-refresh-failed",
} satisfies Record<ShellChangeKind, string>;

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

const scheduleRetry = (kind: ShellChangeKind): void => {
  cancelRetry();
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    reload(kind, false);
  }, retrySchedule.next());
};

const refreshFailureCode = (cause: unknown, kind: ShellChangeKind): string => {
  if (cause instanceof RuntimeConfigRequestError || cause instanceof StylesheetRefreshError) {
    return cause.code;
  }
  return REFRESH_FAILURE_CODES[kind];
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
    code: refreshFailureCode(cause, operation.kind),
    severity: transient ? "warning" : "error",
    message: errorMessage(cause),
    hint: refreshFailureHint(cause, transient),
    view: supportView(operation.target.supportUrl) ?? "",
  };
};

const connectEvents = (): void => {
  developmentEvents.connect(
    appendUrlPath(getSupportUrl(), "dev/events", globalThis.location.href),
    reconcileBaseline,
    (kind) => {
      if (globalThis.__MARIMO_STUDIO_RUNTIME_STATE__ === "failed") {
        globalThis.location.reload();
        return;
      }
      reload(kind);
    },
  );
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
    if (operation.kind === "html" || operation.kind === "views") {
      shellRefreshState.rememberFailure(operation.target);
    }
    if (failure.state === "loading") {
      showDiagnostic(failure.diagnostic, "waiting");
      scheduleRetry(operation.kind);
      return;
    }
    resetRetry();
    showDiagnostic(failure.diagnostic);
    console.error("marimo-studio presentation refresh error", error);
  },
  onReady: (operation) => {
    resetRetry();
    clearDiagnostic();
    shellRefreshState.complete(operation.target);
  },
  onSupportChanged: connectEvents,
};

const reload = (kind: ShellChangeKind, resetBackoff = true): void => {
  if (kind === "views" && !shellRefreshState.pending) {
    return;
  }
  if (resetBackoff) {
    resetRetry();
  } else {
    cancelRetry();
  }
  if (kind === "css" && !shellRefreshState.pending) {
    void presentationRevisions.refreshStyles(revisionPolicy).catch(() => {});
    return;
  }
  if (kind === "runtime" && !shellRefreshState.pending) {
    void presentationRevisions.refreshRuntime(revisionPolicy).catch(() => {});
    return;
  }
  const target = shellRefreshState.targetForChange(kind, {
    documentUrl: presentationRevisions.url,
    supportUrl: getSupportUrl(),
  });
  if (target) {
    void presentationRevisions
      .transition(target.documentUrl, target.supportUrl, kind, revisionPolicy)
      .catch(() => {});
  }
};

function reconcileBaseline(): void {
  if (baselineReconciler.ready()) {
    reload("html");
  }
}

const transitionToView = (documentUrl: string, supportUrl: string): void => {
  resetRetry();
  shellRefreshState.supersede();
  void presentationRevisions
    .transition(documentUrl, supportUrl, "html", revisionPolicy)
    .catch(() => {});
};

const startDevelopmentReload = async (): Promise<void> => {
  presentationRevisions = await waitForPresentationRevisions();
  subscribeRuntimeConfig(() => {
    notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
    if (baselineReconciler.configure()) {
      reload("html");
    }
  });
  if (hasRuntimeConfig()) {
    notifyDiagnostics(getRuntimeConfig().diagnostics, getRuntimeConfig().view);
  }
  const unbindViewSwitches = bindViewSwitches((request) => {
    transitionToView(request.documentUrl, request.supportUrl);
  });
  const unbindViewNavigation = bindViewNavigation((request) => {
    transitionToView(request.documentUrl, getSupportUrl());
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
      presentationRevisions.dispose();
      developmentEvents.close();
      unbindViewSwitches();
      unbindViewNavigation();
    },
    { once: true },
  );
};

void startDevelopmentReload();
