import type { RuntimeRegistry } from "@marimo-studio/runtime";

import htmx from "htmx.org";

import { documentBase } from "./document/base";
import { bindViewNavigation } from "./document/events";
import { startQuerySync } from "./document/query-sync";
import { presentationRevisions, presentationSessionId } from "./document/revision-runtime";
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

const browser = globalThis as typeof globalThis & Window;
const runtimeSessionId = presentationSessionId;
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

const showRuntimeError = (error: unknown) => {
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "failed";
  setRuntimeConnectionState("error", {
    code: error instanceof RuntimeConfigRequestError ? error.code : "runtime-bootstrap-failed",
    message: errorMessage(error),
    hint:
      error instanceof RuntimeConfigRequestError
        ? error.hint
        : "Reload the view after the runtime is available.",
  });
  console.error("marimo-studio runtime error", error);
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

const bindStandaloneViewNavigation = (): (() => void) =>
  bindViewNavigation((request) => {
    void presentationRevisions
      .transition(request.documentUrl, getSupportUrl())
      .catch((error: unknown) => {
        console.error("marimo-studio view navigation error", error);
      });
  });

const bootstrap = async (registry: RuntimeRegistry) => {
  startPresentationObservers(updateConfiguredRuntimeQuery);
  globalThis.addEventListener("pagehide", stopPresentationObservers, { once: true });
  await initializeViewStyles();
  projectionHosts.register();

  let config = await loadRuntimeConfig(runtimeSessionId);
  config = await presentationRevisions.resume(config);
  const stopRuntimeNavigation = bindRuntimeNavigation();
  const stopViewNavigation = config.dev ? () => {} : bindStandaloneViewNavigation();
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
  if (session.sessionId) {
    presentationRevisions.rememberSession(session.sessionId);
    globalThis.addEventListener(
      "pagehide",
      () => presentationRevisions.rememberSession(session.sessionId ?? ""),
      { once: true },
    );
  }
};

const start = (registry: RuntimeRegistry) => {
  void bootstrap(registry).catch((error: unknown) => {
    if (error instanceof RuntimeMountCancelledError) {
      return;
    }
    if (error instanceof RuntimeConfigRequestError && error.transient) {
      setRuntimeConnectionState("connecting", {
        code: error.code,
        message: error.message,
        hint: error.hint || "Wait for the notebook session to settle.",
      });
      if (error.code === "presentation-revision-mismatch") {
        setTimeout(() => globalThis.location.reload(), 250);
      } else {
        setTimeout(() => start(registry), 1_000);
      }
      return;
    }
    showRuntimeError(error);
  });
};

export const startPresentation = (registry: RuntimeRegistry): void => {
  start(registry);
};
