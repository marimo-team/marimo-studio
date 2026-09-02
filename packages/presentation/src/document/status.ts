import type {
  ViewDiagnosticsMessage,
  ViewErrorMessage,
  ViewSyncPendingMessage,
} from "@marimo-studio/protocol/preview-messages";

import type { PresentationDiagnostic } from "../diagnostics.ts";

import { toBrowserDiagnostic, toBrowserDiagnostics } from "../readiness-diagnostics.ts";
import {
  getRuntimeConfig,
  getMountConfig,
  getSupportUrl,
  hasRuntimeConfig,
  type ProjectionDiagnostic,
} from "../runtime-config/index.ts";
import { documentLifecycleEnvelope } from "./document-lifecycle-id.ts";
import { postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";

const runtimeId = (): string =>
  hasRuntimeConfig() ? getRuntimeConfig().runtime.id : getMountConfig().runtime;

export const supportView = (supportUrl = getSupportUrl()): string => {
  try {
    const path = new URL(supportUrl, globalThis.location.origin).pathname;
    const value = path.split("/").filter(Boolean).at(-1);
    return value ? decodeURIComponent(value) : "";
  } catch {
    return "";
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
  host.hidden = state === "waiting" && studioOwned();
  const message: ViewSyncPendingMessage | ViewErrorMessage = {
    type: state === "waiting" ? "marimo-studio:view-sync-pending" : "marimo-studio:view-error",
    runtime: runtimeId(),
    ...documentLifecycleEnvelope(),
    diagnostic: toBrowserDiagnostic(detail),
    view: detail.view,
  };
  postToStudioParent(message);
};

export const clearDiagnostic = (): void => {
  const host = diagnosticHost();
  host.hidden = true;
  delete host.dataset.state;
  host.removeAttribute("title");
};

export const notifyDiagnostics = (
  diagnostics: ProjectionDiagnostic[],
  view = supportView(),
): void => {
  const message: ViewDiagnosticsMessage = {
    type: "marimo-studio:view-diagnostics",
    runtime: runtimeId(),
    ...documentLifecycleEnvelope(),
    view,
    diagnostics: toBrowserDiagnostics(diagnostics),
  };
  postToStudioParent(message);
};

const diagnosticHost = (): HTMLElement => {
  const existing = document.querySelector<HTMLElement>("[data-marimo-studio-diagnostic]");
  if (existing) {
    return existing;
  }
  const created = document.createElement("div");
  created.dataset.marimoStudioDiagnostic = "";
  created.setAttribute("role", "alert");
  created.hidden = true;
  document.body.append(created);
  return created;
};
