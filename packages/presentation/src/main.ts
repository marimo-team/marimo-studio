import type { RuntimeRegistry } from "@marimo-studio/runtime";

import htmx from "htmx.org";

import { registerMarimoCellElement } from "./cells/host";
import { bindViewNavigation } from "./document/events";
import { PresentationDocument } from "./document/presentation";
import { startQuerySync } from "./document/query-sync";
import {
  finishSessionRefresh,
  prepareSessionRefresh,
  rememberSession,
} from "./document/session-preservation";
import { errorMessage } from "./errors";
import { setRuntimeConnectionState, startReadiness } from "./readiness";
import {
  commitRuntimeConfig,
  fetchRuntimeConfigForRevision,
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
  updateConfiguredRuntime,
  updateConfiguredRuntimeQuery,
} from "./runtime/coordinator";
import { restorePendingRuntimeSelection } from "./runtime/selection";
import { startValueBindings } from "./values/index";
import { initializeViewStyles } from "./view-styles/runtime";

declare global {
  interface Window {
    htmx: typeof htmx;
    __MARIMO_STUDIO_SESSION_ID__?: string;
    __MARIMO_STUDIO_RUNTIME_STATE__?: "booting" | "failed" | "mounted";
  }
}

const browser = globalThis as typeof globalThis & Window;
const presentationDocument = new PresentationDocument();
let activeViewTransition: AbortController | undefined;
browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "booting";
restorePendingRuntimeSelection();
startQuerySync();

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
    activeViewTransition?.abort();
    const controller = new AbortController();
    activeViewTransition = controller;
    void presentationDocument
      .replace(request.documentUrl, getSupportUrl(), controller.signal, () => {})
      .then(() => {
        if (updateConfiguredRuntime(getRuntimeConfig()) === "reload") {
          globalThis.location.reload();
        }
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        console.error("marimo-studio view navigation error", error);
      })
      .finally(() => {
        if (activeViewTransition === controller) {
          activeViewTransition = undefined;
        }
      });
  });

const bootstrap = async (registry: RuntimeRegistry) => {
  await initializeViewStyles();
  startReadiness(updateConfiguredRuntimeQuery);
  registerMarimoCellElement();
  (globalThis as typeof globalThis & Window).htmx = htmx;

  let config = await loadRuntimeConfig();
  const stopRuntimeNavigation = bindRuntimeNavigation();
  const stopViewNavigation = config.dev ? () => {} : bindStandaloneViewNavigation();
  globalThis.addEventListener("pagehide", stopRuntimeNavigation, { once: true });
  globalThis.addEventListener("pagehide", stopViewNavigation, { once: true });
  globalThis.addEventListener("pagehide", () => activeViewTransition?.abort(), { once: true });
  const resumingDocument = prepareSessionRefresh(config);
  if (resumingDocument) {
    config = commitRuntimeConfig(
      await fetchRuntimeConfigForRevision(
        getSupportUrl(),
        config.revision,
        undefined,
        config.runtime.id,
      ),
    );
    document.addEventListener("marimo-studio:runtime-ready", () => finishSessionRefresh(), {
      once: true,
    });
  }
  startValueBindings();
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
    rememberSession(config, session.sessionId);
    globalThis.addEventListener(
      "pagehide",
      () => rememberSession(getRuntimeConfig(), session.sessionId ?? ""),
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
