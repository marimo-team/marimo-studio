import type { ReplayDocumentMessage } from "@marimo-studio/protocol/preview-messages";
import type { RuntimeRegistry } from "@marimo-studio/runtime";

import { bootstrapSession } from "@marimo-studio/marimo-frontend/session-bootstrap";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import htmx from "htmx.org";

import { documentBase } from "./document/base";
import {
  activeDocumentLifecycleId,
  documentLifecycleEnvelope,
} from "./document/document-lifecycle-id.ts";
import { bindFragmentRestores, bindViewNavigation } from "./document/events";
import { startFrameRuntimeBridge } from "./document/frame-runtime-bridge.ts";
import { onFinalPageHide } from "./document/page-lifecycle";
import { postToStudioParent } from "./document/parent-bridge.ts";
import { bindRuntimeQueryHistory, startQuerySync } from "./document/query-sync";
import { waitForReceiverAdmission } from "./document/receiver-admission.ts";
import { presentationRefreshUrl, presentationRenewalSupportUrl } from "./document/refresh-url.ts";
import { createPresentationRevisions } from "./document/revision-runtime";
import { BrowserSessionReplay } from "./document/session-preservation";
import {
  bootstrapPresentationSession,
  PresentationDocumentRetiredError,
} from "./document/session-startup";
import { supportView } from "./document/status.ts";
import {
  setTrustedRuntimeQuery,
  type TrustedRuntimeSelection,
  viewHistoryNavigationForUrl,
} from "./document/view-navigation.ts";
import { errorMessage } from "./errors";
import { startPresentationObservers, stopPresentationObservers } from "./observers";
import { projectionHosts } from "./projections/host-runtime";
import { setRuntimeConnectionState } from "./rendered-view-observer";
import {
  commitRuntimeConfig,
  fetchCurrentRuntimeConfig,
  getRuntimeConfig,
  getMountConfig,
  getSupportUrl,
  hasRuntimeConfig,
  loadRuntimeConfig,
  runtimeConfigSessionId,
  RuntimeConfigRequestError,
} from "./runtime-config/index";
import {
  disposeConfiguredRuntime,
  mountConfiguredRuntime,
  RuntimeMountCancelledError,
  updateConfiguredRuntimeQuery,
} from "./runtime/coordinator";
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
const documentLifetime = new AbortController();
onFinalPageHide(() => documentLifetime.abort(new PresentationDocumentRetiredError()));
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

const renewalToken = (documentUrl: string): string | undefined => {
  const url = new URL(documentUrl, globalThis.location.href);
  const marker = "/_marimo-studio/presentation/";
  const boundary = url.pathname.lastIndexOf(marker);
  const token =
    boundary < 0
      ? url.searchParams.get("marimo_studio_renewal")
      : url.pathname.slice(boundary + marker.length).split("/", 1)[0];
  return token?.startsWith("d.") ? token : undefined;
};

const ownedViewDocumentUrl = (
  presentationRevisions: ReturnType<typeof createPresentationRevisions>,
  publicUrl: string,
  view: string,
  trustedRuntime: TrustedRuntimeSelection,
): string => {
  const source = new URL(publicUrl, globalThis.location.href);
  const token = renewalToken(presentationRevisions.url);
  if (token) {
    source.searchParams.set("marimo_studio_renewal", token);
  }
  const config = getRuntimeConfig();
  setTrustedRuntimeQuery(source, trustedRuntime);
  return presentationRefreshUrl(
    {
      presentationSessionId: config.presentationSessionId,
      supportUrl: config.supportUrl,
      view,
    },
    source.href,
  );
};

const bindRuntimeNavigation = (
  presentationRevisions: ReturnType<typeof createPresentationRevisions>,
): (() => void) => {
  const runtimeExplicit = getMountConfig().runtimeExplicit;
  const reloadWhenChanged = () => {
    if (!hasRuntimeConfig()) {
      return;
    }
    const config = getRuntimeConfig();
    const historyNavigation = viewHistoryNavigationForUrl({
      href: globalThis.location.href,
      origin: globalThis.location.origin,
      publicRootUrl: config.publicRootUrl,
      documentRootUrl: config.documentRootUrl,
      publicQuery: publicNotebookQuery(globalThis.location.search),
      trustedRuntime: { id: config.runtime.id, explicit: runtimeExplicit },
      views: config.views,
      currentView: config.view,
      mountedDocumentUrl: presentationRevisions.url,
    });
    if (!historyNavigation) {
      return;
    }
    const { navigation, publicQueryChanged } = historyNavigation;
    const target = new URL(navigation.documentUrl);
    if (publicQueryChanged) {
      globalThis.location.assign(target.href);
      return;
    }
    const documentUrl = ownedViewDocumentUrl(presentationRevisions, target.href, navigation.view, {
      id: config.runtime.id,
      explicit: runtimeExplicit,
    });
    void presentationRevisions
      .restore(documentUrl, getSupportUrl(), target.href)
      .catch((cause: unknown) => console.error("marimo-studio history navigation error", cause));
  };
  globalThis.addEventListener("popstate", reloadWhenChanged);
  return () => {
    globalThis.removeEventListener("popstate", reloadWhenChanged);
  };
};

const bindStandaloneViewNavigation = (
  presentationRevisions: ReturnType<typeof createPresentationRevisions>,
): (() => void) => {
  const runtimeExplicit = getMountConfig().runtimeExplicit;
  return bindViewNavigation(async (request) => {
    const config = getRuntimeConfig();
    const trustedRuntime = { id: config.runtime.id, explicit: runtimeExplicit };
    const documentUrl = ownedViewDocumentUrl(
      presentationRevisions,
      request.documentUrl,
      request.view,
      trustedRuntime,
    );
    try {
      const commit = await (globalThis.parent === globalThis.window
        ? presentationRevisions.navigate(documentUrl, getSupportUrl(), request.documentUrl)
        : presentationRevisions.restore(documentUrl, getSupportUrl(), request.documentUrl));
      if (!commit || commit.reloadDocument) {
        return false;
      }
      const replayUrl = new URL(presentationRevisions.url, globalThis.location.href);
      setTrustedRuntimeQuery(replayUrl, trustedRuntime);
      const runtimeSessionId = runtimeConfigSessionId({
        connected: globalThis.__MARIMO_STUDIO_SESSION_ID__,
      });
      if (runtimeSessionId) {
        replayUrl.searchParams.set("session_id", runtimeSessionId);
      }
      const replay: ReplayDocumentMessage = {
        type: "marimo-studio:replay-document",
        runtime: config.runtime.id,
        ...documentLifecycleEnvelope(),
        view: config.view,
        url: replayUrl.href,
      };
      postToStudioParent(replay);
      return true;
    } catch (cause) {
      console.error("marimo-studio view navigation error", cause);
      return false;
    }
  }, runtimeExplicit);
};

const loadPresentationRuntimeConfig = async (
  runtimeSessionId?: string,
  signal = documentLifetime.signal,
) => {
  const mount = getMountConfig();
  const view = supportView(mount.supportUrl);
  if (!view) {
    return await loadRuntimeConfig(runtimeSessionId, signal);
  }
  const documentUrl = presentationRefreshUrl(
    {
      presentationSessionId: mount.sessionId,
      supportUrl: mount.supportUrl,
      view,
    },
    globalThis.location.href,
    runtimeSessionId,
  );
  const renewalSupportUrl = presentationRenewalSupportUrl(documentUrl, mount.supportUrl);
  if (renewalSupportUrl === new URL(mount.supportUrl, globalThis.location.href).href) {
    try {
      return await loadRuntimeConfig(runtimeSessionId, signal);
    } catch (cause) {
      if (
        !(cause instanceof RuntimeConfigRequestError) ||
        cause.code !== "presentation-revision-unavailable"
      ) {
        throw cause;
      }
    }
  }
  return commitRuntimeConfig(
    await fetchCurrentRuntimeConfig(
      documentUrl,
      renewalSupportUrl,
      mount.runtime,
      mount.sessionId,
      runtimeSessionId,
      signal,
    ),
  );
};

const bootstrap = async (registry: RuntimeRegistry, signal = documentLifetime.signal) => {
  const browserSessionReplay = new BrowserSessionReplay();
  await initializeViewStyles(undefined, signal);
  if (signal.aborted) {
    throw signal.reason;
  }
  const mount = getMountConfig();
  const startup = await bootstrapPresentationSession({
    bootstrap: bootstrapSession,
    loadConfig: (runtimeSessionId) => loadPresentationRuntimeConfig(runtimeSessionId, signal),
    replay: browserSessionReplay,
    requiresSessionForConfig: false,
    signal,
  });
  const presentationRevisions = createPresentationRevisions(
    startup.sessionId,
    mount.sessionId ?? startup.sessionId,
    browserSessionReplay,
  );
  onFinalPageHide(() => presentationRevisions.dispose());
  projectionHosts.register();
  if (startup.config.dev) {
    const admissionLifetime = new AbortController();
    const retireAdmission = () => admissionLifetime.abort(signal.reason);
    if (signal.aborted) {
      retireAdmission();
    } else {
      signal.addEventListener("abort", retireAdmission, { once: true });
    }
    const admission = waitForReceiverAdmission(
      {
        lifecycleId: activeDocumentLifecycleId(),
        runtime: startup.config.runtime.id,
        view: startup.config.view,
        revision: () => getRuntimeConfig().revision,
      },
      undefined,
      admissionLifetime.signal,
    );
    // Transition teardown can retire admission before control reaches its await.
    // Observe the original promise immediately while preserving its rejection below.
    void admission.catch(() => {});
    try {
      const refreshed = await presentationRevisions.transition(
        presentationRevisions.url,
        getSupportUrl(),
      );
      const settled = await presentationRevisions.waitUntilIdle();
      if (refreshed?.reloadDocument || settled?.reloadDocument) {
        return;
      }
      const admitted = await admission;
      const admittedTransition = await presentationRevisions.waitUntilIdle();
      if (admittedTransition?.reloadDocument) {
        return;
      }
      if (admitted && admitted.revision !== getRuntimeConfig().revision) {
        throw new RuntimeConfigRequestError(
          "The Studio preview admission was superseded before runtime startup.",
          "presentation-revision-mismatch",
          true,
        );
      }
    } finally {
      signal.removeEventListener("abort", retireAdmission);
      admissionLifetime.abort();
    }
  }
  if (startup.replaying && globalThis.parent === globalThis.window) {
    document.addEventListener("marimo-studio:runtime-ready", () => browserSessionReplay.finish(), {
      once: true,
    });
  }
  startPresentationObservers(updateConfiguredRuntimeQuery);
  onFinalPageHide(stopPresentationObservers);
  const config = getRuntimeConfig();
  const livePresentation = config.presentationSessionId !== undefined;
  const stopRuntimeNavigation = livePresentation
    ? bindRuntimeNavigation(presentationRevisions)
    : () => {};
  const stopViewNavigation =
    config.dev || !livePresentation
      ? () => {}
      : bindStandaloneViewNavigation(presentationRevisions);
  const stopFragmentRestores = bindFragmentRestores();
  onFinalPageHide(stopRuntimeNavigation);
  onFinalPageHide(stopViewNavigation);
  onFinalPageHide(stopFragmentRestores);
  projectionHosts.connect();
  onFinalPageHide(() => projectionHosts.disconnect());
  const runtimeRoot = document.querySelector<HTMLElement>("#marimo-runtime-root");
  if (!runtimeRoot) {
    throw new Error("Missing #marimo-runtime-root");
  }
  onFinalPageHide(disposeConfiguredRuntime);
  const session = await mountConfiguredRuntime(registry, config, runtimeRoot);
  if (session.update(getRuntimeConfig()) === "reload") {
    globalThis.location.reload();
    return;
  }
  const stopStaticQueryHistory = livePresentation
    ? () => {}
    : bindRuntimeQueryHistory((query) => session.updateQuery(query));
  onFinalPageHide(stopStaticQueryHistory);
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "mounted";
  const stopFrameBridge = startFrameRuntimeBridge(session.sessionId ?? null);
  onFinalPageHide(stopFrameBridge);
  const sessionId = session.sessionId;
  if (sessionId) {
    presentationRevisions.rememberSession(sessionId);
    onFinalPageHide(() => presentationRevisions.rememberSession(sessionId));
  }
};

const start = (registry: RuntimeRegistry) => {
  const signal = documentLifetime.signal;
  void bootstrap(registry, signal).catch((cause: unknown) => {
    if (signal.aborted && signal.reason instanceof PresentationDocumentRetiredError) {
      return;
    }
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
        setTimeout(() => {
          if (!signal.aborted) {
            globalThis.location.reload();
          }
        }, 250);
      } else {
        setTimeout(() => {
          if (!signal.aborted) {
            start(registry);
          }
        }, 1_000);
      }
      return;
    }
    showRuntimeError(cause);
  });
};

export const startPresentation = (registry: RuntimeRegistry): void => {
  start(registry);
};
