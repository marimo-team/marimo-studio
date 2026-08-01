import {
  getSupportUrl,
  type PresentationDiagnostic,
  type ProjectionDiagnostic,
} from "./runtime-config.ts";

export const supportView = (
  supportUrl = getSupportUrl(),
): string | undefined => {
  try {
    const path = new URL(supportUrl, globalThis.location.origin).pathname;
    const value = path.split("/").filter(Boolean).at(-1);
    return value ? decodeURIComponent(value) : undefined;
  } catch {
    return undefined;
  }
};

export const showDiagnostic = (
  detail: PresentationDiagnostic,
  state: "error" | "waiting" = "error",
): void => {
  const host = diagnosticHost();
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

export const clearDiagnostic = (): void => {
  const host = diagnosticHost();
  host.hidden = true;
  delete host.dataset.state;
  host.removeAttribute("title");
};

export const notifyReady = (view = supportView()): void => {
  globalThis.parent.postMessage(
    {
      type: "marimo-studio:view-ready",
      view,
      sessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
    },
    globalThis.location.origin,
  );
};

export const notifyDiagnostics = (
  diagnostics: ProjectionDiagnostic[],
  view = supportView(),
): void => {
  globalThis.parent.postMessage(
    {
      type: "marimo-studio:view-diagnostics",
      view,
      diagnostics,
    },
    globalThis.location.origin,
  );
};

const diagnosticHost = (): HTMLElement => {
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
