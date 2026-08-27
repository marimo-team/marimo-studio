import type {
  ReceiverReadyMessage,
  ReceiverUnreadyMessage,
} from "@marimo-studio/protocol/preview-messages";

import { afterEach, expect, test, vi } from "vite-plus/test";

import { documentLifecycleEnvelope } from "../src/document/document-lifecycle-id.ts";
import { bindPresentationEvents } from "../src/document/events.ts";
import { bindDocumentPresence, onFinalPageHide } from "../src/document/page-lifecycle.ts";
import { startQuerySync } from "../src/document/query-sync.ts";
import { PresentationDocumentRetiredError } from "../src/document/session-startup.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { commitRuntimeConfig, getRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  clientId: "client-123456789",
  lifecycleId: 7,
};

const pageTransition = (type: "pagehide" | "pageshow", persisted: boolean): void => {
  const event = new Event(type);
  Object.defineProperty(event, "persisted", { value: persisted });
  globalThis.dispatchEvent(event);
};

afterEach(() => {
  projectionHosts.disconnect();
  document.body.replaceChildren();
  globalThis.history.replaceState({}, "", "/");
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("final cleanup ignores persisted page transitions", () => {
  const retirement = new PresentationDocumentRetiredError();
  const lifetime = new AbortController();
  const unbind = onFinalPageHide(() => lifetime.abort(retirement));

  pageTransition("pagehide", true);
  expect(lifetime.signal.aborted).toBe(false);
  pageTransition("pageshow", true);
  expect(lifetime.signal.aborted).toBe(false);
  pageTransition("pagehide", false);
  pageTransition("pagehide", false);
  expect(lifetime.signal.aborted).toBe(true);
  expect(lifetime.signal.reason).toBe(retirement);
  unbind();
});

test("a persisted page retains projection, query, and refresh capabilities", () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.history.replaceState({}, "", "/?marimo_studio_lifecycle=7");
  const frame = document.createElement("iframe");
  frame.dataset.previewFrame = "";
  vi.stubGlobal("frameElement", frame);
  const parent = { postMessage: vi.fn() };
  vi.stubGlobal("parent", parent);
  const pushState = globalThis.history.pushState;
  const replaceState = globalThis.history.replaceState;
  startQuerySync();
  const refresh = vi.fn();
  const stopRefresh = bindPresentationEvents({ changed: refresh, refresh: vi.fn() });
  document.body.innerHTML = '<marimo-cell name="summary" data-state="ready"></marimo-cell>';
  projectionHosts.connect();
  document.querySelector<HTMLElement>("marimo-cell")!.dataset.state = "ready";
  const disconnectProjections = vi.spyOn(projectionHosts, "disconnect");
  const dispose = vi.fn(() => {
    stopRefresh();
    projectionHosts.disconnect();
    globalThis.history.pushState = pushState;
    globalThis.history.replaceState = replaceState;
  });
  const unbind = bindDocumentPresence({
    ready: () => {
      const message = {
        type: "marimo-studio:receiver-ready",
        runtime: "server",
        ...documentLifecycleEnvelope(),
        view: "dashboard",
        revision: getRuntimeConfig().revision,
      } satisfies ReceiverReadyMessage;
      parent.postMessage(message, globalThis.location.origin);
    },
    unready: () => {
      const message = {
        type: "marimo-studio:receiver-unready",
        runtime: "server",
        ...documentLifecycleEnvelope(),
        view: "dashboard",
      } satisfies ReceiverUnreadyMessage;
      parent.postMessage(message, globalThis.location.origin);
    },
    dispose,
  });

  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:receiver-ready",
      lifecycleId: 7,
      revision: "presentation-revision",
    }),
    globalThis.location.origin,
  );
  parent.postMessage.mockClear();
  pageTransition("pagehide", true);
  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:receiver-unready", lifecycleId: 7 }),
    globalThis.location.origin,
  );
  expect(dispose).not.toHaveBeenCalled();
  expect(disconnectProjections).not.toHaveBeenCalled();

  pageTransition("pageshow", true);
  expect(parent.postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:receiver-ready",
      lifecycleId: 7,
      revision: "presentation-revision",
    }),
    globalThis.location.origin,
  );
  expect(projectionHosts.states()).toEqual(["ready"]);

  parent.postMessage.mockClear();
  globalThis.history.pushState({}, "", "/?region=apac");
  expect(parent.postMessage).toHaveBeenCalledWith(
    {
      type: "marimo-studio:query-change",
      runtime: "server",
      lifecycleId: 7,
      query: "?region=apac",
    },
    globalThis.location.origin,
  );
  const presentationChange = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data: {
      type: "marimo-studio:presentation-change",
      runtime: "server",
      lifecycleId: 7,
      view: "dashboard",
    },
  });
  Object.defineProperty(presentationChange, "source", { value: parent });
  globalThis.dispatchEvent(presentationChange);
  expect(refresh).toHaveBeenCalledOnce();

  pageTransition("pagehide", false);
  expect(dispose).toHaveBeenCalledOnce();
  expect(disconnectProjections).toHaveBeenCalledOnce();
  unbind();
});
