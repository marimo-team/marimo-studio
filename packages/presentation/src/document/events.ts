import {
  parsePresentationBuild,
  parsePresentationRefreshBarrierResult,
  parseWorkspaceChange,
  type PresentationBuild,
  type PresentationRefreshBarrierResult,
} from "@marimo-studio/protocol/development-events";
import {
  EVENT_SOCKET_REJECTED,
  EVENT_SOCKET_RETIRED,
  eventSocketUrl,
  parseStudioEvent,
} from "@marimo-studio/protocol/event-socket";
import {
  parsePreviewMessage,
  type NavigateViewMessage,
  type PresentationRefreshMessage,
  type SwitchViewMessage,
} from "@marimo-studio/protocol/preview-messages";
import {
  publicNotebookQuery,
  PRESENTATION_REVISION_QUERY_PARAM,
  UNFRAMED_QUERY_PARAM,
} from "@marimo-studio/protocol/query";
import { parsePresentationBaseline } from "@marimo-studio/protocol/source-events";

import { getMountConfig, getRuntimeConfig, hasRuntimeConfig } from "../runtime-config/index.ts";
import {
  activeDocumentLifecycleId,
  documentLifecycleEnvelope,
  setActiveDocumentLifecycleId,
} from "./document-lifecycle-id.ts";
import { isStudioParentMessage, postToStudioParent } from "./parent-bridge.ts";
import { RefreshRetrySchedule } from "./presentation-refresh.ts";
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

// The server closes the socket with EVENT_SOCKET_RETIRED or a 4xx status when
// it no longer accepts this page, for example after the view was removed.
// Network drops and server errors leave the subscription worth reopening.
const rejected = (code: number): boolean =>
  code === EVENT_SOCKET_RETIRED ||
  (code >= EVENT_SOCKET_REJECTED + 400 && code < EVENT_SOCKET_REJECTED + 500);

const SOCKET_CONNECTING = 0;

// Closing a socket before its handshake completes logs a browser error, so a
// connecting socket closes once it opens.
const closeSocket = (socket: WebSocket): void => {
  if (socket.readyState === SOCKET_CONNECTING) {
    socket.addEventListener("open", () => socket.close(), { once: true });
    return;
  }
  socket.close();
};

export class DevelopmentEvents {
  private source: WebSocket | undefined;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private readonly reconnects = new RefreshRetrySchedule();

  /**
   * Subscribe to development events and reopen the socket after a network
   * failure. `onRejected` runs when the server refuses the page, with whether
   * this subscription was ready before.
   */
  connect(
    url: string,
    onReady: (revision?: string | null) => void,
    onPresentation: () => void,
    onBuild: (build: PresentationBuild) => void = () => {},
    onDisconnected: () => void = () => {},
    onRejected: (wasReady: boolean) => void = onDisconnected,
  ): void {
    this.close();
    this.reconnects.reset();
    let wasReady = false;
    const open = () => {
      const source = new WebSocket(eventSocketUrl(url, globalThis.location.href));
      this.source = source;
      const current = (operation: () => void) => {
        if (this.source === source) {
          operation();
        }
      };
      source.addEventListener("message", (message) => {
        const frame = parseStudioEvent(message.data);
        if (frame?.event === "ready") {
          const baseline = parsePresentationBaseline(frame.data);
          current(() => {
            wasReady = true;
            this.reconnects.reset();
            onReady(baseline?.revision);
          });
        } else if (frame?.event === "change") {
          const change = parseWorkspaceChange(frame.data);
          const build = change === "build" ? parsePresentationBuild(frame.data) : undefined;
          if (change === "presentation") {
            current(onPresentation);
          } else if (build) {
            current(() => onBuild(build));
          }
        }
      });
      source.addEventListener("close", (event) =>
        current(() => {
          this.source = undefined;
          if (rejected(event.code)) {
            onRejected(wasReady);
            return;
          }
          onDisconnected();
          this.retry = setTimeout(open, this.reconnects.next());
        }),
      );
    };
    open();
  }

  close(): void {
    clearTimeout(this.retry);
    this.retry = undefined;
    if (this.source) {
      closeSocket(this.source);
    }
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
      (!hasRuntimeConfig() || request.runtime === getRuntimeConfig().runtime.id)
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
  readonly refresh: (
    phase: PresentationRefreshMessage["phase"],
    diagnostic?: PresentationRefreshMessage["diagnostic"],
  ) => void;
  readonly barrier?: (
    port: MessagePort,
    generation: number,
    signal: AbortSignal,
    result: Promise<PresentationRefreshBarrierResult>,
  ) => void;
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
          const controller = new AbortController();
          let finishResult = (_result: PresentationRefreshBarrierResult) => {};
          const result = new Promise<PresentationRefreshBarrierResult>((resolve) => {
            finishResult = resolve;
          });
          let resultFinished = false;
          const finish = (outcome: PresentationRefreshBarrierResult) => {
            if (resultFinished) {
              return;
            }
            resultFinished = true;
            if (outcome.type === "marimo-studio:presentation-refresh-barrier-failed") {
              controller.abort(
                new DOMException("The parent abandoned the document mutation.", "AbortError"),
              );
            }
            finishResult(outcome);
            port.close();
          };
          port.addEventListener("message", (message) => {
            const outcome = parsePresentationRefreshBarrierResult(message.data);
            if (outcome?.generation !== request.generation) {
              return;
            }
            finish(outcome);
          });
          port.addEventListener("messageerror", () =>
            finish({
              schema: 1,
              type: "marimo-studio:presentation-refresh-barrier-failed",
              generation: request.generation,
            }),
          );
          port.start();
          if (callbacks.barrier) {
            callbacks.barrier(port, request.generation, controller.signal, result);
          } else {
            port.close();
          }
        }
      } else {
        callbacks.refresh(request.phase, request.diagnostic);
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
      publicRootUrl: config.publicRootUrl,
      documentRootUrl: config.documentRootUrl,
      publicQuery: publicNotebookQuery(globalThis.location.search),
      trustedRuntime: { id: config.runtime.id, explicit: runtimeExplicit },
      unframed: new URLSearchParams(globalThis.location.search).get(UNFRAMED_QUERY_PARAM) === "1",
      views: config.views,
      currentView: config.view,
      clientId: getMountConfig().clientId,
      supportUrl: config.supportUrl,
      exactRevision: new URLSearchParams(globalThis.location.search).get(
        PRESENTATION_REVISION_QUERY_PARAM,
      ),
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
