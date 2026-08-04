import { parseShellChange, type ShellChangeKind } from "@marimo-studio/protocol/development-events";
import {
  parsePreviewMessage,
  type NavigateViewMessage,
  type SwitchViewMessage,
} from "@marimo-studio/protocol/preview-messages";

import { getRuntimeConfig, hasRuntimeConfig } from "../runtime-config/index.ts";
import { viewNavigationForUrl } from "./view-navigation.ts";

export class DevelopmentEvents {
  private source: EventSource | undefined;

  connect(url: string, onReady: () => void, onChange: (kind: ShellChangeKind) => void): void {
    this.close();
    this.source = new EventSource(url);
    this.source.addEventListener("ready", onReady);
    this.source.addEventListener("change", (event) => {
      const payload = parseShellChange((event as MessageEvent<string>).data);
      if (payload) {
        onChange(payload);
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
    const request = parsePreviewMessage(event.data);
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

export const bindViewNavigation = (): (() => void) => {
  const listener = (event: MouseEvent) => {
    if (
      globalThis.parent === globalThis.window ||
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
      rootUrl: config.rootUrl,
      views: config.views,
      currentView: config.view,
    });
    if (!navigation) {
      return;
    }
    event.preventDefault();
    if (!navigation.current) {
      const message: NavigateViewMessage = {
        type: "marimo-studio:navigate-view",
        runtime: config.runtime.id,
        view: navigation.view,
      };
      globalThis.parent.postMessage(message, globalThis.location.origin);
    }
  };
  document.addEventListener("click", listener);
  return () => document.removeEventListener("click", listener);
};
