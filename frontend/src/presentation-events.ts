import { getRuntimeConfig, hasRuntimeConfig } from "./runtime-config.ts";
import type { ShellChangeKind } from "./shell-refresh-state.ts";
import { viewNavigationForUrl } from "./view-navigation.ts";

export interface ViewSwitchRequest {
  view: string;
  documentUrl: string;
  supportUrl: string;
}

export class DevelopmentEvents {
  private source: EventSource | undefined;

  connect(
    url: string,
    onReady: () => void,
    onChange: (kind: ShellChangeKind) => void,
  ): void {
    this.close();
    this.source = new EventSource(url);
    this.source.addEventListener("ready", onReady);
    this.source.addEventListener("change", (event) => {
      const payload = parseChange((event as MessageEvent<string>).data);
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

export const bindViewSwitches = (
  callback: (request: ViewSwitchRequest) => void,
): () => void => {
  const listener = (event: MessageEvent<unknown>) => {
    if (
      event.origin !== globalThis.location.origin ||
      event.source !== globalThis.parent
    ) {
      return;
    }
    const request = parseViewSwitch(event.data);
    if (request) {
      callback(request);
    }
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

export const bindViewNavigation = (): () => void => {
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
      runtimeUrl: config.runtimeUrl,
      views: config.views,
      currentView: config.view,
    });
    if (!navigation) {
      return;
    }
    event.preventDefault();
    if (!navigation.current) {
      globalThis.parent.postMessage(
        { type: "marimo-studio:navigate-view", view: navigation.view },
        globalThis.location.origin,
      );
    }
  };
  document.addEventListener("click", listener);
  return () => document.removeEventListener("click", listener);
};

const parseChange = (source: string): ShellChangeKind | undefined => {
  try {
    const value = JSON.parse(source) as { kind?: unknown };
    return value.kind === "html" ||
        value.kind === "css" ||
        value.kind === "runtime" ||
        value.kind === "views"
      ? value.kind
      : undefined;
  } catch {
    return undefined;
  }
};

const parseViewSwitch = (data: unknown): ViewSwitchRequest | undefined => {
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
    return undefined;
  }
  return {
    view: data.view,
    documentUrl: data.documentUrl,
    supportUrl: data.supportUrl,
  };
};
