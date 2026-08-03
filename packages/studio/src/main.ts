import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { z } from "zod";

import type { Surface } from "./layout/model.ts";

import { LayoutController } from "./layout/controller.ts";
import { surfaceSchema } from "./layout/schema.ts";
import { PreviewController } from "./preview/controller.ts";
import { SourceController } from "./source/controller.ts";
import { ViewController } from "./views/controller.ts";
import { createViewRemote } from "./views/remote.ts";
import { ViewTransition } from "./views/transition.ts";

const required = <T extends Element>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Studio markup is missing ${selector}`);
  }
  return element;
};

const studio = required<HTMLElement>("[data-studio]");
const workspace = required<HTMLElement>("[data-workspace]");
const editor = required<HTMLIFrameElement>("[data-editor-frame]");
const preview = required<HTMLIFrameElement>("[data-preview-frame]");
const popout = required<HTMLAnchorElement>("[data-preview-popout]");
const status = required<HTMLElement>("[data-studio-status]");
const dividerLayer = required<HTMLElement>("[data-divider-layer]");
const scrim = required<HTMLElement>("[data-resize-scrim]");
const compactTabs = required<HTMLElement>("[data-compact-tabs]");

const routeConfigSchema = z.object({
  eventsUrl: z.string().min(1),
  viewsUrl: z.string().min(1),
  viewPrefix: z.string().min(1),
  studioPrefix: z.string().min(1),
  supportPrefix: z.string().min(1),
  workspaceId: z.string().min(1),
  serverToken: z.string().min(1),
  initialView: z.string().trim().min(1),
});
const {
  eventsUrl,
  viewsUrl,
  viewPrefix,
  studioPrefix,
  supportPrefix,
  workspaceId,
  serverToken,
  initialView,
} = routeConfigSchema.parse({
  eventsUrl: studio.dataset.eventsUrl,
  viewsUrl: studio.dataset.viewsUrl,
  viewPrefix: studio.dataset.viewPrefix,
  studioPrefix: studio.dataset.studioPrefix,
  supportPrefix: studio.dataset.supportPrefix,
  workspaceId: studio.dataset.workspaceId,
  serverToken: studio.dataset.serverToken,
  initialView: required<HTMLElement>("[data-view-trigger-label]").textContent,
});

const panes = new Map<Surface, HTMLElement>(
  surfaceSchema.options.map((surface) => [
    surface,
    required<HTMLElement>(`[data-surface="${surface}"]`),
  ]),
);
const storagePrefix = `marimo-studio:layout:v1:${workspaceId}`;
let notebookQuery = publicNotebookQuery(globalThis.location.search);
const viewUrl = (view: string) => `${viewPrefix}${view}/${notebookQuery}`;
const studioUrl = (view: string) => `${studioPrefix}${view}/${notebookQuery}`;
const supportUrl = (view: string) => `${supportPrefix}/${view}`;
const syncNotebookQuery = (query: string) => {
  const next = publicNotebookQuery(query);
  if (next === notebookQuery) {
    return;
  }
  notebookQuery = next;
  const url = new URL(globalThis.location.href);
  url.search = next;
  globalThis.history.replaceState(
    globalThis.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
};

const controllers: {
  source?: SourceController;
  preview?: PreviewController;
  views?: ViewController;
} = {};

const layout = new LayoutController(
  workspace,
  dividerLayer,
  scrim,
  panes,
  compactTabs,
  storagePrefix,
  initialView,
  () => {
    controllers.source?.requestMeasure();
    controllers.preview?.requestResize();
  },
);

controllers.preview = new PreviewController(
  initialView,
  editor,
  preview,
  popout,
  status,
  viewUrl,
  supportUrl,
  syncNotebookQuery,
  (view) => void controllers.views?.choose(view),
);

controllers.source = await SourceController.create(
  supportPrefix,
  serverToken,
  initialView,
  storagePrefix,
  () => layout.reveal("source"),
);

const initialViews = Array.from(
  document.querySelectorAll<HTMLElement>("[data-view-option]"),
  (option) => option.dataset.viewOption,
);
const parsedInitialViews = z.array(z.string()).parse(initialViews);

const transition = new ViewTransition(initialView, {
  prepare: async (view) => await controllers.source!.switchView(view),
  commit: (view, created) => {
    layout.switchView(view, created);
    controllers.preview?.switchView(view);
    globalThis.history.replaceState({}, "", studioUrl(view));
    if (created) {
      controllers.source?.focusHtml();
    }
  },
  cancel: () => controllers.source?.cancelSwitch(),
});
controllers.views = new ViewController(
  initialView,
  parsedInitialViews,
  createViewRemote(viewsUrl, serverToken),
  eventsUrl,
  (view, created) => transition.select(view, created),
  () => controllers.source!.prepareViewChange(),
  (view) => globalThis.location.assign(studioUrl(view)),
);

const protectPendingSource = (event: BeforeUnloadEvent) => {
  if (controllers.source?.hasPendingChanges) {
    event.preventDefault();
  }
};
globalThis.addEventListener("beforeunload", protectPendingSource);

globalThis.addEventListener(
  "pagehide",
  () => {
    controllers.views?.dispose();
    controllers.source?.dispose();
    controllers.preview?.dispose();
    layout.dispose();
    globalThis.removeEventListener("beforeunload", protectPendingSource);
  },
  { once: true },
);
