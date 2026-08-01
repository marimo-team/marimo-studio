import { LayoutController } from "./studio/layout-controller.ts";
import { PreviewController } from "./studio/preview-controller.ts";
import { SourceController } from "./studio/source-controller.ts";
import type { Surface } from "./studio/layout.ts";
import { ViewTransition } from "./studio/view-transition.ts";
import { ViewController } from "./studio/view-controller.ts";
import { createViewRemote } from "./studio/view-remote.ts";

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

const eventsUrl = studio.dataset.eventsUrl;
const viewsUrl = studio.dataset.viewsUrl;
const viewPrefix = studio.dataset.viewPrefix;
const studioPrefix = studio.dataset.studioPrefix;
const supportPrefix = studio.dataset.supportPrefix;
const workspaceId = studio.dataset.workspaceId;
const serverToken = studio.dataset.serverToken;
const initialView = required<HTMLElement>("[data-view-trigger-label]")
  .textContent?.trim();
if (
  !eventsUrl ||
  !viewsUrl ||
  !viewPrefix ||
  !studioPrefix ||
  !supportPrefix ||
  !workspaceId ||
  !serverToken ||
  !initialView
) {
  throw new Error("Studio route configuration is incomplete");
}

const panes = new Map<Surface, HTMLElement>(
  (["notebook", "source", "preview"] as Surface[]).map((surface) => [
    surface,
    required<HTMLElement>(`[data-surface="${surface}"]`),
  ]),
);
const storagePrefix = `marimo-studio:layout:v1:${workspaceId}`;
const viewUrl = (view: string) => `${viewPrefix}${view}/`;
const studioUrl = (view: string) => `${studioPrefix}${view}/`;
const supportUrl = (view: string) => `${supportPrefix}/${view}`;

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
).filter((view): view is string => typeof view === "string");

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
  initialViews,
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
