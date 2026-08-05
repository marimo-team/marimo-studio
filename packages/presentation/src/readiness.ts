import type {
  ViewErrorMessage,
  ViewReadyMessage,
  ViewSyncPendingMessage,
} from "@marimo-studio/protocol/preview-messages";

import type {
  HostDiagnostic,
  PresentationDiagnostic,
  RuntimeDiagnostic,
  StudioDiagnostic,
} from "./diagnostics.ts";

import {
  getRuntimeConfig,
  getRuntimeDiagnostics,
  getMountConfig,
  getSupportUrl,
  hasRuntimeConfig,
  requestedRuntimeId,
} from "./runtime-config/index.ts";

type RuntimeConnectionState = "connecting" | "ready" | "error";
type PresentationRefreshState = "ready" | "loading" | "error";
export type PageReadinessState = "connecting" | "loading" | "ready" | "error";

interface MarimoStudioApi {
  ready: () => Promise<void>;
  diagnostics: () => readonly StudioDiagnostic[];
  updateQuery: (query: string) => Promise<void>;
}

interface Deferred {
  promise: Promise<void>;
  resolve: () => void;
}

const deferred = (): Deferred => {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

let connectionState: RuntimeConnectionState = "connecting";
let runtimeDiagnostic: RuntimeDiagnostic | undefined;
let presentationState: PresentationRefreshState = "ready";
let presentationDiagnostic: PresentationDiagnostic | undefined;
let presentationGeneration = 0;
let waiter = deferred();
let settled = false;
let pageState: PageReadinessState = "connecting";
let observer: MutationObserver | undefined;
let readinessGeneration = 0;

const runtimeView = (): string => {
  if (hasRuntimeConfig()) {
    return getRuntimeConfig().view;
  }
  try {
    return decodeURIComponent(
      new URL(getSupportUrl(), globalThis.location.origin).pathname
        .split("/")
        .filter(Boolean)
        .at(-1) ?? "",
    );
  } catch {
    return "";
  }
};

const runtimeDiagnosticHost = (): HTMLElement => {
  const existing = document.querySelector<HTMLElement>("[data-marimo-studio-runtime-diagnostic]");
  if (existing) {
    return existing;
  }
  const host = document.createElement("div");
  host.dataset.marimoStudioRuntimeDiagnostic = "";
  host.setAttribute("role", "alert");
  host.hidden = true;
  document.body.append(host);
  return host;
};

const publishRuntimeDiagnostic = () => {
  const host = runtimeDiagnosticHost();
  if (!runtimeDiagnostic) {
    host.hidden = true;
    return;
  }
  host.textContent = runtimeDiagnostic.message;
  host.dataset.state = runtimeDiagnostic.severity === "warning" ? "waiting" : "error";
  host.setAttribute("role", runtimeDiagnostic.severity === "warning" ? "status" : "alert");
  host.title = runtimeDiagnostic.hint;
  host.hidden = runtimeDiagnostic.severity === "warning" && globalThis.parent !== globalThis.window;
  const message: ViewSyncPendingMessage | ViewErrorMessage = {
    type:
      runtimeDiagnostic.severity === "warning"
        ? "marimo-studio:view-sync-pending"
        : "marimo-studio:view-error",
    runtime: hasRuntimeConfig()
      ? getRuntimeConfig().runtime.id
      : requestedRuntimeId(getMountConfig().runtime),
    message: runtimeDiagnostic.message,
    hint: runtimeDiagnostic.hint,
    view: runtimeDiagnostic.view,
  };
  globalThis.parent.postMessage(message, globalThis.location.origin);
};

const hostState = (host: Element): string => {
  return (host as HTMLElement).dataset.state ?? "connecting";
};

export const pageReadinessState = (
  connection: RuntimeConnectionState,
  hostStates: string[],
  presentation: PresentationRefreshState = "ready",
): PageReadinessState => {
  if (connection === "error" || presentation === "error") {
    return "error";
  }
  if (connection !== "ready") {
    return "connecting";
  }
  if (presentation === "loading") {
    return "loading";
  }
  if (hostStates.some((state) => ["connecting", "loading"].includes(state))) {
    return "loading";
  }
  if (hostStates.some((state) => ["error", "missing"].includes(state))) {
    return "error";
  }
  return "ready";
};

const evaluate = () => {
  const cells = Array.from(document.querySelectorAll("marimo-cell"));
  const values = Array.from(document.querySelectorAll("[mo-value]"));
  const hosts = [...cells, ...values];
  const hostStates = hosts.map(hostState);
  const next = pageReadinessState(connectionState, hostStates, presentationState);

  document.documentElement.dataset.marimoStudioState = next;
  const nextSettled =
    connectionState === "error" ||
    presentationState === "error" ||
    (connectionState === "ready" &&
      presentationState === "ready" &&
      !hostStates.some((state) => ["connecting", "loading", "stale"].includes(state)));
  if (!nextSettled && settled) {
    waiter = deferred();
  }
  if (nextSettled && !settled) {
    waiter.resolve();
    document.dispatchEvent(
      new CustomEvent("marimo-studio:idle", {
        detail: { state: next },
      }),
    );
  }
  if (next === "ready" && pageState !== "ready") {
    const message: ViewReadyMessage = {
      type: "marimo-studio:view-ready",
      runtime: hasRuntimeConfig()
        ? getRuntimeConfig().runtime.id
        : requestedRuntimeId(getMountConfig().runtime),
      view: runtimeView(),
      revision: hasRuntimeConfig() ? getRuntimeConfig().revision : getMountConfig().revision,
      sessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
    };
    globalThis.parent.postMessage(message, globalThis.location.origin);
  }
  pageState = next;
  settled = nextSettled;
};

export const notifyReadinessChanged = () => {
  const generation = readinessGeneration;
  queueMicrotask(() => {
    if (generation === readinessGeneration) {
      evaluate();
    }
  });
};

export const setRuntimeConnectionState = (
  state: RuntimeConnectionState,
  diagnostic?: Pick<RuntimeDiagnostic, "code" | "hint" | "message">,
) => {
  const previous = connectionState;
  connectionState = state;
  if (diagnostic) {
    runtimeDiagnostic = {
      ...diagnostic,
      scope: "runtime",
      severity: state === "error" ? "error" : "warning",
      view: runtimeView(),
    };
    publishRuntimeDiagnostic();
  } else if (state === "ready") {
    runtimeDiagnostic = undefined;
    publishRuntimeDiagnostic();
  }
  if (state === "ready" && previous !== "ready") {
    document.dispatchEvent(new CustomEvent("marimo-studio:runtime-ready"));
  }
  notifyReadinessChanged();
};

export const beginPresentationRefresh = (): number => {
  presentationGeneration += 1;
  presentationState = "loading";
  presentationDiagnostic = undefined;
  notifyReadinessChanged();
  return presentationGeneration;
};

export const setPresentationRefreshState = (
  generation: number,
  state: PresentationRefreshState,
  diagnostic?: PresentationDiagnostic,
) => {
  if (generation !== presentationGeneration) {
    return;
  }
  presentationState = state;
  presentationDiagnostic = diagnostic;
  notifyReadinessChanged();
};

const diagnostics = (): readonly StudioDiagnostic[] => {
  const configured = hasRuntimeConfig() ? getRuntimeDiagnostics() : [];
  const configuredKeys = new Set(
    configured.map((diagnostic) => `${diagnostic.code}\u0000${diagnostic.target}`),
  );
  const view = hasRuntimeConfig() ? getRuntimeConfig().view : "";
  const hostDiagnostics = Array.from(
    document.querySelectorAll<HTMLElement>("[data-marimo-diagnostic-code]"),
  ).flatMap((host): HostDiagnostic[] => {
    const code = host.dataset.marimoDiagnosticCode;
    const message = host.dataset.marimoDiagnosticMessage;
    const target = host.getAttribute("name") ?? host.getAttribute("mo-value") ?? "";
    if (!code || !message || configuredKeys.has(`${code}\u0000${target}`)) {
      return [];
    }
    return [
      {
        scope: "host",
        code,
        severity: "error",
        message,
        hint: host.dataset.marimoDiagnosticHint ?? "",
        view,
        target,
      },
    ];
  });
  return [
    ...configured,
    ...hostDiagnostics,
    ...(runtimeDiagnostic ? [{ ...runtimeDiagnostic }] : []),
    ...(presentationDiagnostic ? [{ ...presentationDiagnostic }] : []),
  ];
};

export const startReadiness = (updateQuery: (query: string) => Promise<void>) => {
  document.documentElement.dataset.marimoStudioState = "connecting";
  globalThis.marimoStudio = {
    ready: () => {
      evaluate();
      return settled ? Promise.resolve() : waiter.promise;
    },
    diagnostics,
    updateQuery,
  };
  observer?.disconnect();
  observer = new MutationObserver(notifyReadinessChanged);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-state", "mo-value", "name"],
    childList: true,
    subtree: true,
  });
  notifyReadinessChanged();
};

export const stopReadiness = () => {
  readinessGeneration += 1;
  observer?.disconnect();
  observer = undefined;
};

declare global {
  var marimoStudio: MarimoStudioApi;

  interface Window {
    marimoStudio: MarimoStudioApi;
  }
}
