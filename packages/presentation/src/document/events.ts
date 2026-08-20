import {
  parsePresentationBuild,
  parseWorkspaceChange,
  type PresentationBuild,
} from "@marimo-studio/protocol/development-events";
import {
  parsePreviewMessage,
  type NavigateViewMessage,
  type PresentationRefreshMessage,
  type SwitchViewMessage,
} from "@marimo-studio/protocol/preview-messages";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { getMountConfig, getRuntimeConfig, hasRuntimeConfig } from "../runtime-config/index.ts";
import {
  activeDocumentLifecycleId,
  documentLifecycleEnvelope,
  setActiveDocumentLifecycleId,
} from "./document-lifecycle-id.ts";
import { isStudioParentMessage, postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";
import { viewNavigationForUrl } from "./view-navigation.ts";

export interface DirectViewNavigation {
  documentUrl: string;
  view: string;
}

const scrollToFragment = (hash: string): void => {
  let identifier = hash.startsWith("#") ? hash.slice(1) : hash;
  try {
    identifier = decodeURIComponent(identifier);
  } catch {
    return;
  }
  try {
    (
      document.getElementById(identifier) ?? document.getElementsByName(identifier)[0]
    )?.scrollIntoView();
  } catch {
    return;
  }
};

const replaceFragment = (hash: string): void => {
  const target = new URL(globalThis.location.href);
  target.hash = hash;
  globalThis.history.replaceState(globalThis.history.state, "", target);
  scrollToFragment(hash);
};

export const bindFragmentRestores = (): (() => void) => {
  const listener = (event: MessageEvent<unknown>) => {
    if (!isStudioParentMessage(event)) {
      return;
    }
    const request = parsePreviewMessage(event.data);
    if (
      request?.type !== "marimo-studio:restore-fragment" ||
      !hasRuntimeConfig() ||
      request.runtime !== getRuntimeConfig().runtime.id ||
      request.lifecycleId !== activeDocumentLifecycleId()
    ) {
      return;
    }
    replaceFragment(request.hash);
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

export class DevelopmentEvents {
  private source: EventSource | undefined;

  connect(
    url: string,
    onReady: () => void,
    onPresentation: () => void,
    onBuild: (build: PresentationBuild) => void = () => {},
  ): void {
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
      if (this.source !== source) {
        return;
      }
      if (!(event instanceof MessageEvent)) {
        return;
      }
      const data = event.data;
      const change = parseWorkspaceChange(data);
      if (change === "presentation") {
        current(onPresentation);
      } else if (change === "build") {
        const build = parsePresentationBuild(data);
        if (build) {
          current(() => onBuild(build));
        }
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
    if (!isStudioParentMessage(event)) {
      return;
    }
    const request = parsePreviewMessage(event.data);
    if (
      request?.type === "marimo-studio:switch-view" &&
      (!hasRuntimeConfig() || request.runtime === getRuntimeConfig().runtime.descriptor.id)
    ) {
      setActiveDocumentLifecycleId(request.lifecycleId);
      callback(request);
    }
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

interface PresentationEventCallbacks {
  readonly changed: () => void;
  readonly refresh: (phase: PresentationRefreshMessage["phase"]) => void;
  readonly barrier?: (port: MessagePort, generation: number) => void;
}

export const bindPresentationEvents = (callbacks: PresentationEventCallbacks): (() => void) => {
  const listener = (event: MessageEvent<unknown>) => {
    if (!isStudioParentMessage(event)) {
      return;
    }
    const request = parsePreviewMessage(event.data);
    if (
      (request?.type !== "marimo-studio:presentation-change" &&
        request?.type !== "marimo-studio:presentation-refresh" &&
        request?.type !== "marimo-studio:presentation-refresh-barrier") ||
      !hasRuntimeConfig()
    ) {
      return;
    }
    const config = getRuntimeConfig();
    if (
      request.runtime === config.runtime.id &&
      request.view === config.view &&
      request.lifecycleId === activeDocumentLifecycleId()
    ) {
      if (request.type === "marimo-studio:presentation-change") {
        callbacks.changed();
      } else if (request.type === "marimo-studio:presentation-refresh-barrier") {
        const port = event.ports.length === 1 ? event.ports[0] : undefined;
        if (port) {
          callbacks.barrier?.(port, request.generation);
        }
      } else {
        callbacks.refresh(request.phase);
      }
    }
  };
  globalThis.addEventListener("message", listener);
  return () => globalThis.removeEventListener("message", listener);
};

export const bindViewNavigation = (
  navigate: (request: DirectViewNavigation) => boolean | Promise<boolean>,
  runtimeExplicit = getMountConfig().runtimeExplicit,
): (() => void) => {
  if (getRuntimeConfig().presentationSessionId === undefined) {
    return () => {};
  }
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
    const href = anchor.getAttribute("href");
    if (href === null) {
      return;
    }
    const navigation = viewNavigationForUrl({
      href,
      origin: globalThis.location.origin,
      publicRootUrl: config.publicRootUrl,
      documentRootUrl: config.documentRootUrl,
      publicQuery: publicNotebookQuery(globalThis.location.search),
      trustedRuntime: { id: config.runtime.id, explicit: runtimeExplicit },
      views: config.views,
      currentView: config.view,
    });
    if (!navigation) {
      return;
    }
    event.preventDefault();
    const current = new URL(globalThis.location.href);
    const target = new URL(navigation.documentUrl);
    const queryChanged = publicNotebookQuery(target.search) !== publicNotebookQuery(current.search);
    if (
      globalThis.parent !== globalThis.window &&
      (studioOwned() || getRuntimeConfig().dev || queryChanged)
    ) {
      const message: NavigateViewMessage = {
        type: "marimo-studio:navigate-view",
        runtime: config.runtime.id,
        ...documentLifecycleEnvelope(),
        view: navigation.view,
        query: target.search,
        hash: target.hash,
      };
      postToStudioParent(message);
      return;
    }
    if (navigation.current && !queryChanged && target.hash === current.hash) {
      return;
    }
    if (navigation.current && !queryChanged) {
      if (globalThis.parent === globalThis.window) {
        globalThis.history.pushState(globalThis.history.state, "", target);
        scrollToFragment(target.hash);
      } else {
        replaceFragment(target.hash);
        const message: NavigateViewMessage = {
          type: "marimo-studio:navigate-view",
          runtime: getRuntimeConfig().runtime.id,
          ...documentLifecycleEnvelope(),
          view: navigation.view,
          query: target.search,
          hash: target.hash,
          history: "push",
        };
        postToStudioParent(message);
      }
      return;
    }
    if (queryChanged) {
      globalThis.location.assign(target.href);
      return;
    }
    const committed = Promise.resolve(
      navigate({ documentUrl: target.href, view: navigation.view }),
    );
    if (globalThis.parent !== globalThis.window) {
      void committed.then((ready) => {
        if (!ready) {
          return;
        }
        const message: NavigateViewMessage = {
          type: "marimo-studio:navigate-view",
          runtime: getRuntimeConfig().runtime.id,
          ...documentLifecycleEnvelope(),
          view: navigation.view,
          query: target.search,
          hash: target.hash,
          history: "push",
        };
        postToStudioParent(message);
      });
    } else {
      void committed;
    }
  };
  document.addEventListener("click", listener);
  return () => document.removeEventListener("click", listener);
};
