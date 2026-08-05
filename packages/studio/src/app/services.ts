import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import type { ControlFrameConnector } from "../features/preview/control-sync.ts";

import { PreviewDeck } from "../features/preview/deck.ts";
import { syncEditorQuery } from "../features/preview/query-remote.ts";
import { initialPreviewRuntime } from "../features/preview/runtime.ts";
import { SourceController } from "../features/source-editor/controller.ts";
import { ViewController } from "../features/views/controller.ts";
import { createViewRemote } from "../features/views/remote.ts";
import { ViewTransition } from "../features/views/transition.ts";
import { LayoutController } from "../features/workspace/controller.ts";
import { StudioRoutes } from "./routes.ts";

export interface StudioServices {
  layout: LayoutController;
  preview: PreviewDeck;
  runtimeIds: readonly string[];
  source: SourceController;
  views: ViewController;
  start(editor: HTMLIFrameElement, frames: ReadonlyMap<string, HTMLIFrameElement>): Promise<void>;
  dispose(): void;
}

export const createStudioServices = (
  bootstrap: StudioBootstrap,
  connectControlFrame?: ControlFrameConnector,
): StudioServices => {
  const routes = new StudioRoutes(bootstrap);
  const storagePrefix = `marimo-studio:workspace-layout:v1:${bootstrap.workspaceId}`;
  const runtimeIds = bootstrap.runtimes.map((runtime) => runtime.id);
  const layout = new LayoutController(storagePrefix, bootstrap.selectedView);
  const source = new SourceController(
    bootstrap.urls.viewSupportPrefix,
    bootstrap.serverToken,
    bootstrap.selectedView,
    storagePrefix,
    () => layout.reveal("source"),
  );
  let views: ViewController | undefined;
  const preview = new PreviewDeck({
    initialView: bootstrap.selectedView,
    initialRuntime: initialPreviewRuntime({
      available: runtimeIds,
      configured: bootstrap.defaultRuntime,
    }),
    runtimes: runtimeIds,
    viewUrl: routes.view,
    supportUrl: routes.support,
    syncQuery: routes.syncQuery,
    syncEditorQuery: (query, signal) =>
      syncEditorQuery(bootstrap.urls.query, bootstrap.serverToken, query, signal),
    navigate: (view) => void views?.choose(view, "preserve"),
    connectControlFrame,
  });
  const transition = new ViewTransition(bootstrap.selectedView, {
    prepare: async (view) => await source.switchView(view),
    commit: (view, landing, changed) => {
      layout.switchView(view, landing);
      if (changed) {
        preview.switchView(view);
        globalThis.history.replaceState({}, "", routes.studio(view));
      }
      if (landing === "authoring") {
        source.focusHtml();
      }
    },
    cancel: () => source.cancelSwitch(),
  });
  views = new ViewController(
    bootstrap.selectedView,
    [...bootstrap.views],
    createViewRemote(bootstrap.urls.views, bootstrap.serverToken),
    bootstrap.urls.events,
    (view, landing) => transition.select(view, landing),
    () => source.prepareViewChange(),
    (view) => globalThis.location.assign(routes.studio(view)),
  );
  let disposed = false;

  return {
    layout,
    preview,
    runtimeIds,
    source,
    views,
    async start(editor, frames) {
      preview.attach(editor, frames);
      views.start();
      await source.start();
    },
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      views.dispose();
      source.dispose();
      preview.dispose();
      layout.dispose();
    },
  };
};
