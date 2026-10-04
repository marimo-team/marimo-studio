import { jsonValueSchema, type JsonValue } from "@marimo-studio/protocol/runtime-config";
import { parseStudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import { parseStudioHostBootstrap } from "@marimo-studio/protocol/studio-host";
import { createRoot } from "react-dom/client";

import type { StudioOptions } from "./app/StudioApp.tsx";

import { StudioHost } from "./app/StudioHost.tsx";
import "./style.css";

const required = <T extends Element>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Studio document is missing ${selector}`);
  }
  return element;
};

const readJson = (selector: string): JsonValue => {
  const source = required<HTMLScriptElement>(selector).textContent;
  if (!source) {
    throw new Error(`${selector} is empty`);
  }
  return jsonValueSchema.parse(JSON.parse(source));
};

// Studio records and the document's own URL attributes are references from
// this document. Resolve them before the workspace rewrites history.
const documentUrl = document.baseURI;
for (const icon of document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]')) {
  icon.setAttribute("href", icon.href);
}

const readBootstrap = () => parseStudioBootstrap(readJson("#marimo-studio-bootstrap"), documentUrl);

// Browser automation reads the open workspace here, with absolute URLs. The
// server-authored #marimo-studio-bootstrap record stays as served.
const publishBootstrap = (bootstrap: ReturnType<typeof parseStudioBootstrap>): void => {
  document.documentElement.dataset.marimoStudioState = "ready";
  let element = document.querySelector<HTMLScriptElement>("#marimo-studio-workspace");
  if (!element) {
    element = document.createElement("script");
    element.id = "marimo-studio-workspace";
    element.type = "application/json";
    document.body.append(element);
  }
  element.textContent = JSON.stringify(bootstrap);
};

const showStartupError = (root: HTMLElement, cause: unknown): void => {
  const error = cause instanceof Error ? cause : new Error(String(cause));
  const editorUrl = document.querySelector<HTMLIFrameElement>("#marimo-studio-editor")?.src;
  const message = document.createElement("p");
  message.textContent = error.message;
  const title = document.createElement("strong");
  title.textContent = "Studio could not open";
  const alert = document.createElement("main");
  alert.className = "studio-startup-error";
  alert.setAttribute("role", "alert");
  alert.append(title, message);
  if (editorUrl) {
    const editorLink = document.createElement("a");
    editorLink.className = "studio-native-editor-link";
    editorLink.href = editorUrl;
    editorLink.textContent = "Open notebook editor";
    alert.append(editorLink);
  }
  root.replaceChildren(alert);
  console.error("Studio could not start", error);
};

export const startStudio = (options: StudioOptions): void => {
  const root = required<HTMLElement>("#marimo-studio-root");
  try {
    const host = parseStudioHostBootstrap(readJson("#marimo-studio-host"), documentUrl);
    const editorFrame = required<HTMLIFrameElement>("#marimo-studio-editor");
    const initialBootstrap = host.state === "ready" ? readBootstrap() : undefined;
    if (initialBootstrap) {
      publishBootstrap(initialBootstrap);
    }
    createRoot(root).render(
      <StudioHost
        host={host}
        editorFrame={editorFrame}
        editorSource={editorFrame.src}
        initialBootstrap={initialBootstrap}
        publishBootstrap={publishBootstrap}
        {...options}
      />,
    );
  } catch (error) {
    showStartupError(root, error);
  }
};

export type { StudioOptions } from "./app/StudioApp.tsx";
