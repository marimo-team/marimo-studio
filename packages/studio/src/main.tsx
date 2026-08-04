import { parseStudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import { createRoot } from "react-dom/client";

import { StudioApp, type StudioOptions } from "./StudioApp.tsx";
import "./style.css";

const required = <T extends Element>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Studio document is missing ${selector}`);
  }
  return element;
};

const readBootstrap = () => {
  const source = required<HTMLScriptElement>("#marimo-studio-bootstrap").textContent;
  if (!source) {
    throw new Error("Studio bootstrap is empty");
  }
  return parseStudioBootstrap(JSON.parse(source));
};

const showStartupError = (root: HTMLElement, cause: unknown): void => {
  const error = cause instanceof Error ? cause : new Error(String(cause));
  const editorLink = root
    .querySelector<HTMLAnchorElement>("[data-native-editor-link]")
    ?.cloneNode(true);
  const message = document.createElement("p");
  message.textContent = error.message;
  const title = document.createElement("strong");
  title.textContent = "Studio could not open";
  const alert = document.createElement("main");
  alert.className = "studio-startup-error";
  alert.setAttribute("role", "alert");
  alert.append(title, message);
  if (editorLink) {
    alert.append(editorLink);
  }
  root.replaceChildren(alert);
  console.error("Studio could not start", error);
};

export const startStudio = async (options: StudioOptions): Promise<void> => {
  const root = required<HTMLElement>("#marimo-studio-root");
  try {
    const bootstrap = readBootstrap();
    createRoot(root).render(<StudioApp bootstrap={bootstrap} {...options} />);
  } catch (error) {
    showStartupError(root, error);
  }
};

export type { StudioOptions } from "./StudioApp.tsx";
