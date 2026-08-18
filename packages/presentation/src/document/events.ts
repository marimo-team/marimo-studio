import { parseShellChange, type ShellChangeKind } from "@marimo-studio/protocol/development-events";
import {
  parsePreviewMessage,
  type NavigateViewMessage,
  type SwitchViewMessage,
} from "@marimo-studio/protocol/preview-messages";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { messageJson } from "../json.ts";
import { getRuntimeConfig, hasRuntimeConfig } from "../runtime-config/index.ts";
import { viewNavigationForUrl } from "./view-navigation.ts";

export interface DirectViewNavigation {
  documentUrl: string;
  view: string;
}

export class DevelopmentEvents {
  private source: EventSource | undefined;

  connect(url: string, onReady: () => void, onChange: (kind: ShellChangeKind) => void): void {
    this.close();
    const source = new EventSource(url);
    this.source = source;
    const current = (operation: () => void) => {
      if (this.source === source) {
        operation();
      }
    };
    source.addEventListener("ready", () => current(onReady));
    source.addEventListener("change", (event) => {
      if (!(event instanceof MessageEvent)) {
        return;
      }
      const payload = parseShellChange(event.data);
      if (payload) {
        current(() => onChange(payload));
      }
    });
  }

  close(): void {
    this.source?.close();
    this.source = undefined;
  }
}

export const bindViewSwitches = (callback: (request: SwitchViewMessage) => void): (() => void) => {
  const listener = (event: MessageEvent<unknown>) => {
    if (event.origin !== globalThis.location.origin || event.source !== globalThis.parent) {
      return;
    }
    const payload = messageJson(event);
    if (payload === undefined) {
      return;
    }
    const request = parsePreviewMessage(payload);
    if (
      request?.type === "marimo-studio:switch-view" &&
      (!hasRuntimeConfig() || request.runtime === getRuntimeConfig().runtime.id)
    ) {
      callback(request);
    }
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

export const bindSourceChanges = (callback: (kind: ShellChangeKind) => void): (() => void) => {
  const listener = (event: MessageEvent<unknown>) => {
    if (event.origin !== globalThis.location.origin || event.source !== globalThis.parent) {
      return;
    }
    const payload = messageJson(event);
    if (payload === undefined) {
      return;
    }
    const request = parsePreviewMessage(payload);
    if (request?.type !== "marimo-studio:source-change" || !hasRuntimeConfig()) {
      return;
    }
    const config = getRuntimeConfig();
    if (request.runtime === config.runtime.id && request.view === config.view) {
      callback(request.kind);
    }
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

export const bindViewNavigation = (
  navigate: (request: DirectViewNavigation) => void,
): (() => void) => {
  const listener = (event: MouseEvent) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      !(event.target instanceof Element)
    ) {
      return;
    }
    const anchor = event.target.closest<HTMLAnchorElement>("a[href]");
    if (
      !anchor ||
      anchor.hasAttribute("download") ||
      (anchor.target && anchor.target !== "_self") ||
      !hasRuntimeConfig()
    ) {
      return;
    }
    const config = getRuntimeConfig();
    const navigation = viewNavigationForUrl({
      href: anchor.href,
      origin: globalThis.location.origin,
      publicRootUrl: config.publicRootUrl,
      documentRootUrl: config.documentRootUrl,
      publicQuery: publicNotebookQuery(globalThis.location.search),
      views: config.views,
      currentView: config.view,
    });
    if (!navigation) {
      return;
    }
    event.preventDefault();
    const current = new URL(globalThis.location.href);
    const target = new URL(navigation.documentUrl);
    if (navigation.current) {
      if (target.href !== current.href) {
        globalThis.location.assign(target.href);
      }
      return;
    }
    if (target.search !== current.search || target.hash) {
      globalThis.location.assign(target.href);
      return;
    }
    if (globalThis.parent === globalThis.window) {
      navigate({ documentUrl: navigation.documentUrl, view: navigation.view });
      return;
    }
    const message: NavigateViewMessage = {
      type: "marimo-studio:navigate-view",
      runtime: config.runtime.id,
      view: navigation.view,
    };
    globalThis.parent.postMessage(message, globalThis.location.origin);
  };
  document.addEventListener("click", listener);
  return () => document.removeEventListener("click", listener);
};
