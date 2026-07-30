import htmx from "htmx.org";

import { prepareCellHosts } from "./cell-host.ts";
import { notifyPageTheme } from "./page-theme.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getRuntimeConfig,
  getSupportUrl,
  setSupportUrl,
} from "./runtime-config.ts";

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
}

const PAGE_STYLE_SELECTOR =
  'link[rel="stylesheet"]:not([data-marimo-studio-runtime]), style:not([data-marimo-studio-runtime])';

interface StagedStyles {
  commit: () => void;
  discard: () => void;
}

const abortError = () => new DOMException("Refresh superseded", "AbortError");

const isAbortError = (error: unknown): boolean => {
  return error instanceof DOMException && error.name === "AbortError";
};

const supportView = (): string | undefined => {
  try {
    const path = new URL(getSupportUrl(), globalThis.location.origin).pathname;
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

const showDiagnostic = (message: string, view = supportView()) => {
  const host = diagnostic();
  host.textContent = message;
  host.hidden = false;
  globalThis.parent.postMessage(
    { type: "marimo-studio:view-error", message, view },
    globalThis.location.origin,
  );
};

const clearDiagnostic = () => {
  diagnostic().hidden = true;
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
          const loaded = () => {
            signal.removeEventListener("abort", aborted);
            resolve();
          };
          const failed = () => {
            signal.removeEventListener("abort", aborted);
            reject(new Error(`Stylesheet failed to load: ${clone.href}`));
          };
          const aborted = () => reject(abortError());
          clone.addEventListener("load", loaded, { once: true });
          clone.addEventListener("error", failed, { once: true });
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
let transitionGeneration = 0;
let pendingChange: "css" | "html" | undefined;

const reload = (kind: "css" | "html") => {
  if (activeTransition) {
    pendingChange = kind === "html" ? "html" : pendingChange ?? "css";
    return;
  }
  if (kind === "css") {
    void refreshStylesheets().catch((error: unknown) => {
      if (!isAbortError(error)) {
        showDiagnostic(error instanceof Error ? error.message : String(error));
      }
    });
    return;
  }
  void refreshShell()
    .then(() => notifyReady(getRuntimeConfig().view))
    .catch((error: unknown) => {
      if (!isAbortError(error)) {
        showDiagnostic(error instanceof Error ? error.message : String(error));
      }
    });
};

const connectEvents = () => {
  events?.close();
  events = new EventSource(`${getSupportUrl()}/dev/events`);
  events.addEventListener("change", (event) => {
    const data = JSON.parse((event as MessageEvent<string>).data) as {
      kind: "css" | "html" | "views";
    };
    if (data.kind !== "views") {
      reload(data.kind);
    }
  });
};

export const refreshShell = async (
  nextDocumentUrl = documentUrl,
  nextSupportUrl = getSupportUrl(),
) => {
  const generation = ++transitionGeneration;
  activeStyleRefresh?.abort();
  activeTransition?.abort();
  const controller = new AbortController();
  activeTransition = controller;
  let stagedStyles: StagedStyles | undefined;
  try {
    const [response, nextConfig] = await Promise.all([
      fetch(nextDocumentUrl, {
        cache: "no-store",
        signal: controller.signal,
      }),
      fetchRuntimeConfig(nextSupportUrl, controller.signal),
    ]);
    if (!response.ok) {
      const detail = (await response.text()).trim();
      throw new Error(detail || `Shell refresh failed with ${response.status}`);
    }
    const documentSource = await response.text();
    const nextDocument = new DOMParser().parseFromString(
      documentSource,
      "text/html",
    );
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
      setSupportUrl(nextSupportUrl);
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
    if (previousSupportUrl !== nextSupportUrl) {
      connectEvents();
    }
  } finally {
    stagedStyles?.discard();
    if (generation === transitionGeneration) {
      activeTransition = undefined;
      const queued = pendingChange;
      pendingChange = undefined;
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
  void refreshShell(data.documentUrl, data.supportUrl)
    .then(() => notifyReady(view))
    .catch((error: unknown) => {
      if (!isAbortError(error)) {
        showDiagnostic(
          error instanceof Error ? error.message : String(error),
          view,
        );
      }
    });
});

connectEvents();
globalThis.parent.postMessage(
  { type: "marimo-studio:receiver-ready", view: supportView() },
  globalThis.location.origin,
);
globalThis.addEventListener("pagehide", () => events?.close(), { once: true });
