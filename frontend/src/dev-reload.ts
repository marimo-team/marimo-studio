import htmx from "htmx.org";

import { prepareCellHosts } from "./cell-host.ts";
import { notifyPageTheme } from "./page-theme.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getRuntimeConfig,
  getSupportUrl,
  hasRuntimeConfig,
  type PresentationDiagnostic,
  type ProjectionDiagnostic,
  readResponseError,
  requireMatchingPresentationRevision,
  RuntimeConfigRequestError,
  setSupportUrl,
  subscribeRuntimeConfig,
} from "./runtime-config.ts";
import {
  beginPresentationRefresh,
  setPresentationRefreshState,
} from "./readiness.ts";
import {
  BaselineReconciler,
  RefreshRetrySchedule,
  type ShellChangeKind,
  ShellChangeQueue,
  ShellRefreshState,
  type ShellTarget,
} from "./shell-refresh-state.ts";

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
  var __MARIMO_STUDIO_RUNTIME_STATE__:
    | "booting"
    | "failed"
    | "mounted"
    | undefined;
}

const PAGE_STYLE_ATTRIBUTE = "data-marimo-studio-page-style";
const STAGED_STYLE_ATTRIBUTE = "data-marimo-studio-staged-style";
const PAGE_STYLE_SELECTOR = `link[rel="stylesheet"][${PAGE_STYLE_ATTRIBUTE}]` +
  `:not([${STAGED_STYLE_ATTRIBUTE}]), ` +
  `style[${PAGE_STYLE_ATTRIBUTE}]:not([${STAGED_STYLE_ATTRIBUTE}])`;
const STYLESHEET_LOAD_TIMEOUT_MS = 10_000;

const markPageStyles = (root: ParentNode) => {
  root.querySelectorAll<HTMLElement>(
    'head > link[rel="stylesheet"]:not([data-marimo-studio-runtime]), ' +
      "head > style:not([data-marimo-studio-runtime])",
  ).forEach((element) => element.setAttribute(PAGE_STYLE_ATTRIBUTE, ""));
};

markPageStyles(document);

interface StagedStyles {
  commit: () => void;
  discard: () => void;
}

const abortError = () => new DOMException("Refresh superseded", "AbortError");

const isAbortError = (error: unknown): boolean => {
  return error instanceof DOMException && error.name === "AbortError";
};

class StylesheetRefreshError extends Error {
  constructor(
    message: string,
    readonly code:
      | "stylesheet-refresh-failed"
      | "stylesheet-refresh-timeout",
  ) {
    super(message);
    this.name = "StylesheetRefreshError";
  }
}

const supportView = (supportUrl = getSupportUrl()): string | undefined => {
  try {
    const path = new URL(supportUrl, globalThis.location.origin).pathname;
    const value = path.split("/").filter(Boolean).at(-1);
    return value ? decodeURIComponent(value) : undefined;
  } catch {
    return undefined;
  }
};

const diagnostic = (): HTMLElement => {
  const existing = document.querySelector<HTMLElement>(
    "[data-marimo-studio-diagnostic]",
  );
  if (existing) {
    return existing;
  }
  const created = document.createElement("aside");
  created.dataset.marimoStudioDiagnostic = "";
  created.setAttribute("role", "alert");
  created.hidden = true;
  document.body.append(created);
  return created;
};

const showDiagnostic = (
  detail: PresentationDiagnostic,
  state: "error" | "waiting" = "error",
) => {
  const host = diagnostic();
  host.textContent = detail.message;
  if (detail.hint) {
    host.title = detail.hint;
  } else {
    host.removeAttribute("title");
  }
  host.dataset.state = state;
  host.setAttribute("role", state === "waiting" ? "status" : "alert");
  host.hidden = state === "waiting" && globalThis.parent !== globalThis.window;
  globalThis.parent.postMessage(
    {
      type: state === "waiting"
        ? "marimo-studio:view-sync-pending"
        : "marimo-studio:view-error",
      message: detail.message,
      hint: detail.hint,
      view: detail.view,
    },
    globalThis.location.origin,
  );
};

const clearDiagnostic = () => {
  const host = diagnostic();
  host.hidden = true;
  delete host.dataset.state;
  host.removeAttribute("title");
};

const notifyReady = (view = supportView()) => {
  globalThis.parent.postMessage(
    {
      type: "marimo-studio:view-ready",
      view,
      sessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
    },
    globalThis.location.origin,
  );
};

const notifyDiagnostics = (
  diagnostics: ProjectionDiagnostic[],
  view = supportView(),
) => {
  globalThis.parent.postMessage(
    {
      type: "marimo-studio:view-diagnostics",
      view,
      diagnostics,
    },
    globalThis.location.origin,
  );
};

const stylesheetUrl = (
  link: HTMLLinkElement,
  nextDocument: Document,
  documentUrl: string,
): string => {
  const base = nextDocument.querySelector("base")?.getAttribute("href");
  const baseUrl = base
    ? new URL(base, new URL(documentUrl, globalThis.location.href)).toString()
    : new URL(documentUrl, globalThis.location.href).toString();
  const url = new URL(link.getAttribute("href") ?? link.href, baseUrl);
  url.searchParams.set("_marimo_studio_reload", Date.now().toString());
  return url.toString();
};

const stagePageStyles = async (
  nextDocument: Document,
  documentUrl: string,
  signal: AbortSignal,
): Promise<StagedStyles> => {
  const current = Array.from(
    document.querySelectorAll<HTMLElement>(PAGE_STYLE_SELECTOR),
  );
  const staged = Array.from(
    nextDocument.querySelectorAll<HTMLElement>(PAGE_STYLE_SELECTOR),
    (element) => {
      const clone = element.cloneNode(true) as HTMLElement;
      const media = clone.getAttribute("media");
      clone.setAttribute("media", "not all");
      clone.setAttribute(STAGED_STYLE_ATTRIBUTE, "");
      if (clone instanceof HTMLLinkElement) {
        clone.href = stylesheetUrl(clone, nextDocument, documentUrl);
      }
      return { clone, media };
    },
  );
  const discard = () => {
    staged.forEach(({ clone }) => clone.remove());
  };
  if (signal.aborted) {
    throw abortError();
  }
  const loads: Promise<void>[] = [];
  staged.forEach(({ clone }) => {
    if (clone instanceof HTMLLinkElement) {
      loads.push(
        new Promise<void>((resolve, reject) => {
          const settle = (result: () => void) => {
            clearTimeout(timeout);
            clone.removeEventListener("load", loaded);
            clone.removeEventListener("error", failed);
            signal.removeEventListener("abort", aborted);
            result();
          };
          const loaded = () => settle(resolve);
          const failed = () =>
            settle(() =>
              reject(
                new StylesheetRefreshError(
                  `Stylesheet failed to load: ${clone.href}`,
                  "stylesheet-refresh-failed",
                ),
              )
            );
          const aborted = () => settle(() => reject(abortError()));
          const timeout = setTimeout(
            () =>
              settle(() =>
                reject(
                  new StylesheetRefreshError(
                    `Stylesheet did not finish loading: ${clone.href}`,
                    "stylesheet-refresh-timeout",
                  ),
                )
              ),
            STYLESHEET_LOAD_TIMEOUT_MS,
          );
          clone.addEventListener("load", loaded);
          clone.addEventListener("error", failed);
          signal.addEventListener("abort", aborted, { once: true });
        }),
      );
    }
    document.head.append(clone);
  });
  try {
    await Promise.all(loads);
    if (signal.aborted) {
      throw abortError();
    }
  } catch (error) {
    discard();
    throw error;
  }
  return {
    commit: () => {
      current.forEach((element) => element.remove());
      staged.forEach(({ clone, media }) => {
        clone.removeAttribute(STAGED_STYLE_ATTRIBUTE);
        if (media === null) {
          clone.removeAttribute("media");
        } else {
          clone.setAttribute("media", media);
        }
      });
      notifyPageTheme();
    },
    discard,
  };
};

let activeStyleRefresh: AbortController | undefined;

export const refreshStylesheets = async (): Promise<void> => {
  activeStyleRefresh?.abort();
  const controller = new AbortController();
  activeStyleRefresh = controller;
  let staged: StagedStyles | undefined;
  try {
    staged = await stagePageStyles(
      document,
      documentUrl,
      controller.signal,
    );
    if (
      controller.signal.aborted ||
      activeStyleRefresh !== controller
    ) {
      throw abortError();
    }
    staged.commit();
    staged = undefined;
  } finally {
    staged?.discard();
    if (activeStyleRefresh === controller) {
      activeStyleRefresh = undefined;
    }
  }
};

let documentUrl = globalThis.location.href;
let events: EventSource | undefined;
let activeTransition: AbortController | undefined;
let activeConfigRefresh: AbortController | undefined;
let transitionGeneration = 0;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
const retrySchedule = new RefreshRetrySchedule();
let latestRefreshGeneration = 0;
const shellRefreshState = new ShellRefreshState();
const shellChangeQueue = new ShellChangeQueue();
const baselineReconciler = new BaselineReconciler(hasRuntimeConfig());

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

const refreshDiagnostic = (
  error: unknown,
  kind: ShellChangeKind,
  view = supportView(),
): PresentationDiagnostic => {
  const transient = error instanceof RuntimeConfigRequestError &&
    error.transient;
  return {
    scope: "presentation",
    code: error instanceof RuntimeConfigRequestError
      ? error.code
      : error instanceof StylesheetRefreshError
      ? error.code
      : kind === "css"
      ? "stylesheet-refresh-failed"
      : kind === "runtime"
      ? "runtime-config-refresh-failed"
      : "shell-refresh-failed",
    severity: transient ? "warning" : "error",
    message: error instanceof Error ? error.message : String(error),
    hint: error instanceof RuntimeConfigRequestError && error.hint
      ? error.hint
      : transient
      ? "Wait for Marimo to accept the notebook change."
      : "Fix the view source, then save it again.",
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
    commitRuntimeConfig(
      await fetchRuntimeConfig(getSupportUrl(), controller.signal),
    );
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

const completeRefresh = (
  generation: number,
  view = hasRuntimeConfig() ? getRuntimeConfig().view : supportView(),
) => {
  if (generation !== latestRefreshGeneration) {
    return;
  }
  resetRetry();
  clearDiagnostic();
  setPresentationRefreshState(generation, "ready");
  notifyReady(view);
};

const reload = (
  kind: ShellChangeKind,
  resetBackoff = true,
) => {
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
    activeStyleRefresh?.abort();
    const generation = beginRefresh();
    void refreshRuntimeConfig()
      .then(() => completeRefresh(generation))
      .catch((error: unknown) => {
        handleRefreshError(error, kind, generation);
      });
    return;
  }
  const target = shellRefreshState.targetForChange(kind, {
    documentUrl,
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
      handleRefreshError(
        error,
        kind,
        generation,
        supportView(failed.supportUrl),
      );
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
  events?.close();
  events = new EventSource(`${getSupportUrl()}/dev/events`);
  events.addEventListener("ready", reconcileBaseline);
  events.addEventListener("change", (event) => {
    if (globalThis.__MARIMO_STUDIO_RUNTIME_STATE__ === "failed") {
      globalThis.location.reload();
      return;
    }
    const data = JSON.parse((event as MessageEvent<string>).data) as {
      kind: ShellChangeKind;
    };
    reload(data.kind);
  });
};

export const refreshShell = async (
  nextDocumentUrl = documentUrl,
  nextSupportUrl = getSupportUrl(),
) => {
  let target: ShellTarget = {
    documentUrl: nextDocumentUrl,
    supportUrl: nextSupportUrl,
  };
  const generation = ++transitionGeneration;
  activeStyleRefresh?.abort();
  activeConfigRefresh?.abort();
  activeTransition?.abort();
  const controller = new AbortController();
  activeTransition = controller;
  let stagedStyles: StagedStyles | undefined;
  try {
    const response = await fetch(nextDocumentUrl, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const discoveredSupportUrl = response.headers.get(
      "Marimo-Studio-Support-Url",
    );
    if (discoveredSupportUrl) {
      target = {
        documentUrl: nextDocumentUrl,
        supportUrl: discoveredSupportUrl,
      };
    }
    if (!response.ok) {
      const detail = await readResponseError(
        response,
        `Shell refresh failed with ${response.status}`,
      );
      throw new RuntimeConfigRequestError(
        detail.message,
        detail.code,
        detail.transient,
        detail.hint,
      );
    }
    const nextConfig = await fetchRuntimeConfig(
      target.supportUrl,
      controller.signal,
    );
    requireMatchingPresentationRevision(
      response.headers.get("Marimo-Studio-Revision"),
      nextConfig,
    );
    const documentSource = await response.text();
    const nextDocument = new DOMParser().parseFromString(
      documentSource,
      "text/html",
    );
    markPageStyles(nextDocument);
    const current = document.querySelector<HTMLElement>("#app-shell");
    const next = nextDocument.querySelector<HTMLElement>("#app-shell");
    if (!current || !next) {
      throw new Error("Shell refresh requires #app-shell");
    }
    prepareCellHosts(nextDocument);
    stagedStyles = await stagePageStyles(
      nextDocument,
      nextDocumentUrl,
      controller.signal,
    );
    if (
      controller.signal.aborted ||
      generation !== transitionGeneration
    ) {
      throw abortError();
    }

    const previousSupportUrl = getSupportUrl();
    const previousConfig = getRuntimeConfig();
    const previousTitle = document.title;
    const previousDocumentUrl = documentUrl;
    const swap = (
      htmx as unknown as {
        swap: (
          target: Element,
          content: string,
          options: { swapStyle: string },
        ) => void;
      }
    ).swap;
    try {
      setSupportUrl(target.supportUrl);
      commitRuntimeConfig(nextConfig);
      document.title = nextDocument.title;
      globalThis.history.replaceState(
        globalThis.history.state,
        "",
        nextDocumentUrl,
      );
      swap(current, next.outerHTML, { swapStyle: "outerHTML" });
      stagedStyles.commit();
    } catch (error) {
      setSupportUrl(previousSupportUrl);
      commitRuntimeConfig(previousConfig);
      document.title = previousTitle;
      globalThis.history.replaceState(
        globalThis.history.state,
        "",
        previousDocumentUrl,
      );
      stagedStyles.discard();
      throw error;
    }
    documentUrl = nextDocumentUrl;
    stagedStyles = undefined;
    clearDiagnostic();
    if (previousSupportUrl !== target.supportUrl) {
      connectEvents();
    }
    shellRefreshState.complete(target);
  } catch (error) {
    if (!isAbortError(error)) {
      shellRefreshState.rememberFailure(target);
    }
    throw error;
  } finally {
    stagedStyles?.discard();
    if (generation === transitionGeneration) {
      activeTransition = undefined;
      const queued = shellChangeQueue.take();
      if (queued) {
        queueMicrotask(() => reload(queued));
      }
    }
  }
};

globalThis.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.origin !== globalThis.location.origin) {
    return;
  }
  const data = event.data;
  if (
    typeof data !== "object" ||
    data === null ||
    !("type" in data) ||
    data.type !== "marimo-studio:switch-view" ||
    !("view" in data) ||
    typeof data.view !== "string" ||
    !("documentUrl" in data) ||
    typeof data.documentUrl !== "string" ||
    !("supportUrl" in data) ||
    typeof data.supportUrl !== "string"
  ) {
    return;
  }
  const view = data.view;
  resetRetry();
  shellRefreshState.supersede();
  const generation = beginRefresh();
  void refreshShell(data.documentUrl, data.supportUrl)
    .then(() => completeRefresh(generation, view))
    .catch((error: unknown) => {
      handleRefreshError(error, "html", generation, view);
    });
});

connectEvents();
globalThis.parent.postMessage(
  { type: "marimo-studio:receiver-ready", view: supportView() },
  globalThis.location.origin,
);
globalThis.addEventListener(
  "pagehide",
  () => {
    resetRetry();
    activeStyleRefresh?.abort();
    activeConfigRefresh?.abort();
    activeTransition?.abort();
    events?.close();
  },
  { once: true },
);
