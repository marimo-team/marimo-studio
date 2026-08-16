import type { RuntimeRegistry } from "@marimo-studio/runtime";

import { bootstrapSession } from "@marimo-studio/marimo-frontend/session-bootstrap";
import htmx from "htmx.org";

import { documentBase } from "./document/base";
import { bindViewNavigation } from "./document/events";
import { startQuerySync } from "./document/query-sync";
import { createPresentationRevisions } from "./document/revision-runtime";
import { BrowserSessionReplay } from "./document/session-preservation";
import { bootstrapPresentationSession } from "./document/session-startup";
import { errorMessage } from "./errors";
import { startPresentationObservers, stopPresentationObservers } from "./observers";
import { projectionHosts } from "./projections/host-runtime";
import { setRuntimeConnectionState } from "./rendered-view-observer";
import {
  getRuntimeConfig,
  getMountConfig,
  getSupportUrl,
  hasRuntimeConfig,
  loadRuntimeConfig,
  runtimeSelectionChanged,
  RuntimeConfigRequestError,
} from "./runtime-config/index";
import {
  disposeConfiguredRuntime,
  mountConfiguredRuntime,
  RuntimeMountCancelledError,
  updateConfiguredRuntimeQuery,
} from "./runtime/coordinator";
import { restorePendingRuntimeSelection } from "./runtime/selection";
import { initializeViewStyles } from "./view-styles/runtime";

declare global {
  interface Window {
    htmx: typeof htmx;
    __MARIMO_STUDIO_SESSION_ID__?: string;
    __MARIMO_STUDIO_RUNTIME_STATE__?: "booting" | "failed" | "mounted";
  }
}

const browser = window;
browser.htmx = htmx;
const viewBaseUrl = document.baseURI;
// Marimo's server client points <base> at the API root during health checks.
// Keep relative authored assets anchored to the active view directory.
documentBase.start(viewBaseUrl);
browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "booting";
restorePendingRuntimeSelection();
startQuerySync();
globalThis.addEventListener("pagehide", () => documentBase.stop());
globalThis.addEventListener("pageshow", () => documentBase.start());

const showRuntimeError = (cause: unknown) => {
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "failed";
  setRuntimeConnectionState("error", {
    code: cause instanceof RuntimeConfigRequestError ? cause.code : "runtime-bootstrap-failed",
    message: errorMessage(cause),
    hint:
      cause instanceof RuntimeConfigRequestError
        ? cause.hint
        : "Reload the view after the runtime is available.",
  });
  console.error("marimo-studio runtime error", cause);
};

const bindRuntimeNavigation = (): (() => void) => {
  const reloadWhenChanged = () => {
    if (
      hasRuntimeConfig() &&
      runtimeSelectionChanged(getRuntimeConfig().runtime.id, getMountConfig().runtime)
    ) {
      globalThis.location.reload();
    }
  };
  globalThis.addEventListener("popstate", reloadWhenChanged);
  return () => {
    globalThis.removeEventListener("popstate", reloadWhenChanged);
  };
};

const bindStandaloneViewNavigation = (
  presentationRevisions: ReturnType<typeof createPresentationRevisions>,
): (() => void) =>
  bindViewNavigation((request) => {
    void presentationRevisions
      .transition(request.documentUrl, getSupportUrl())
      .catch((cause: unknown) => {
        console.error("marimo-studio view navigation error", cause);
      });
  });

const bootstrap = async (registry: RuntimeRegistry) => {
  const browserSessionReplay = new BrowserSessionReplay();
  const startup = await bootstrapPresentationSession({
    bootstrap: bootstrapSession,
    loadConfig: loadRuntimeConfig,
    replay: browserSessionReplay,
    requiresSessionForConfig: new URL(globalThis.location.href).searchParams.has(
      "marimo_studio_client",
    ),
  });
  const presentationRevisions = createPresentationRevisions(
    startup.sessionId,
    browserSessionReplay,
  );
  if (startup.replaying) {
    document.addEventListener("marimo-studio:runtime-ready", () => browserSessionReplay.finish(), {
      once: true,
    });
  }
  startPresentationObservers(updateConfiguredRuntimeQuery);
  globalThis.addEventListener("pagehide", stopPresentationObservers, { once: true });
  await initializeViewStyles();
  projectionHosts.register();

  const config = startup.config;
  const stopRuntimeNavigation = bindRuntimeNavigation();
  const stopViewNavigation = config.dev
    ? () => {}
    : bindStandaloneViewNavigation(presentationRevisions);
  globalThis.addEventListener("pagehide", stopRuntimeNavigation, { once: true });
  globalThis.addEventListener("pagehide", stopViewNavigation, { once: true });
  globalThis.addEventListener("pagehide", () => presentationRevisions.dispose(), {
    once: true,
  });
  projectionHosts.connect();
  globalThis.addEventListener("pagehide", () => projectionHosts.disconnect(), {
    once: true,
  });
  const runtimeRoot = document.querySelector<HTMLElement>("#marimo-runtime-root");
  if (!runtimeRoot) {
    throw new Error("Missing #marimo-runtime-root");
  }
  globalThis.addEventListener("pagehide", disposeConfiguredRuntime, { once: true });
  const session = await mountConfiguredRuntime(registry, config, runtimeRoot);
  if (session.update(getRuntimeConfig()) === "reload") {
    globalThis.location.reload();
    return;
  }
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "mounted";
  const sessionId = session.sessionId;
  if (sessionId) {
    presentationRevisions.rememberSession(sessionId);
    globalThis.addEventListener(
      "pagehide",
      () => presentationRevisions.rememberSession(sessionId),
      { once: true },
    );
  }
};

const start = (registry: RuntimeRegistry) => {
  void bootstrap(registry).catch((cause: unknown) => {
    if (cause instanceof RuntimeMountCancelledError) {
      return;
    }
    if (cause instanceof RuntimeConfigRequestError && cause.transient) {
      setRuntimeConnectionState("connecting", {
        code: cause.code,
        message: cause.message,
        hint: cause.hint || "Wait for the notebook session to settle.",
      });
      if (cause.code === "presentation-revision-mismatch") {
        setTimeout(() => globalThis.location.reload(), 250);
      } else {
        setTimeout(() => start(registry), 1_000);
      }
      return;
    }
    showRuntimeError(cause);
  });
};

export const startPresentation = (registry: RuntimeRegistry): void => {
  start(registry);
};
