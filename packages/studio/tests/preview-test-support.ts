import type { PresentationToStudioMessage } from "@marimo-studio/protocol/preview-messages";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { vi } from "vite-plus/test";

import type { ControlEndpoint } from "../src/features/preview/control-sync.ts";
import type { PreviewDeck } from "../src/features/preview/deck.ts";

import { PreviewController } from "../src/features/preview/controller.ts";
import { symbolicRuntimeFields } from "./fixtures.ts";

export const frame = (readyState: DocumentReadyState): HTMLIFrameElement => {
  const element = document.createElement("iframe");
  Object.defineProperty(element, "contentDocument", {
    configurable: true,
    value: { readyState },
  });
  Object.defineProperty(element, "contentWindow", {
    configurable: true,
    value: null,
  });
  element.src = "/loaded";
  return element;
};

export const cachedFrames = (
  deck: PreviewDeck,
  primary: Readonly<Record<string, HTMLIFrameElement>>,
): Map<string, HTMLIFrameElement> =>
  new Map(
    deck.frameIds.map((id) => {
      const existing = primary[id];
      if (existing) {
        return [id, existing];
      }
      const cached = frame("complete");
      cached.src = "about:blank";
      return [id, cached];
    }),
  );

export const acknowledgementPort = () => {
  const channel = new MessageChannel();
  return {
    channel,
    port: channel.port1,
    postMessage: vi.spyOn(channel.port1, "postMessage"),
  };
};

export const controller = (
  runtime: string,
  editor: HTMLIFrameElement,
  preview: HTMLIFrameElement,
  viewUrl: (view: string, runtime: string) => string,
  report = vi.fn(),
  navigate = vi.fn(),
  syncQuery = vi.fn(),
) =>
  new PreviewController(
    "dashboard",
    runtime,
    editor,
    preview,
    viewUrl,
    (view) => `/support/${view}`,
    syncQuery,
    vi.fn(async () => "accepted" as const),
    navigate,
    report,
  );

export const dispatchPreviewMessage = <Source>(
  source: Source,
  data: PresentationToStudioMessage,
): void => {
  const event = new MessageEvent("message", {
    origin: globalThis.location.origin,
    data,
  });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

export const dispatchPreviewRefreshHandshake = <Source>(
  source: Source,
  identity: {
    lifecycleId: number;
    revision: string;
    runtime: string;
    view: string;
  },
): void => {
  dispatchPreviewMessage(source, {
    type: "marimo-studio:receiver-unready",
    runtime: identity.runtime,
    lifecycleId: identity.lifecycleId,
    view: identity.view,
  });
  dispatchPreviewMessage(source, {
    type: "marimo-studio:receiver-ready",
    ...identity,
  });
};

export const runtimeConfig = (runtime: string) =>
  ({
    schema: 1,
    revision: "revision-1",
    projectionRevision: "a".repeat(64),
    view: "dashboard",
    views: ["dashboard"],
    runtime: {
      id: runtime,
      instance: `${runtime}-instance`,
      data: {},
    },
    rootUrl: "/",
    publicRootUrl: "/",
    documentRootUrl: "/",
    supportUrl: "/support/dashboard",
    showCellLogs: true,
    ...symbolicRuntimeFields,
    diagnostics: [],
    appConfig: {},
    userConfig: {},
    configOverrides: {},
    dev: true,
    mode: "edit",
  }) satisfies RuntimeConfig;

export const controlEndpoint = (): ControlEndpoint => ({
  snapshot: () => [],
  subscribe: () => () => {},
  apply: vi.fn(async () => {}),
  dispose: vi.fn(),
});
