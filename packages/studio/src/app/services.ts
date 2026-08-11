import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import type { ControlFrameConnector } from "../features/preview/control-sync.ts";

import { PreviewDeck } from "../features/preview/deck.ts";
import { createBrowserObservationRemote } from "../features/preview/observation-remote.ts";
import { syncEditorQuery } from "../features/preview/query-remote.ts";
import { initialPreviewRuntime } from "../features/preview/runtime.ts";
import { SourceController } from "../features/source-editor/controller.ts";
import { ViewController } from "../features/views/controller.ts";
import { createViewRemote } from "../features/views/remote.ts";
import { ViewTransition } from "../features/views/transition.ts";
import { LayoutController } from "../features/workspace/controller.ts";
import { createViewActivationRemote } from "./activation-remote.ts";
import { StudioRoutes } from "./routes.ts";
import { WorkspaceEventCoordinator } from "./workspace-event-coordinator.ts";

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
    routes.support,
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
    syncEditorQuery: (query, operationId, signal) =>
      syncEditorQuery(
        routes.endpoint(bootstrap.urls.query),
        bootstrap.serverToken,
        bootstrap.clientId,
        query,
        operationId,
        signal,
      ),
    navigate: (view) => void views?.choose(view, "preserve"),
    recordObservation: createBrowserObservationRemote(
      routes.support,
      bootstrap.serverToken,
      bootstrap.clientId,
    ),
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
    createViewRemote(routes.endpoint(bootstrap.urls.views), bootstrap.serverToken),
    (view, landing) => transition.select(view, landing),
    () => source.prepareViewChange(),
    (view) => globalThis.location.assign(routes.studio(view)),
  );
  const workspaceEvents = new WorkspaceEventCoordinator({
    eventsUrl: routes.endpoint(bootstrap.urls.events),
    views,
    preview,
    acknowledge: createViewActivationRemote(
      routes.endpoint(bootstrap.urls.agent),
      bootstrap.serverToken,
      bootstrap.clientId,
    ),
  });
  let disposed = false;

  return {
    layout,
    preview,
    runtimeIds,
    source,
    views,
    async start(editor, frames) {
      preview.attach(editor, frames);
      workspaceEvents.start();
      await source.start();
    },
    dispose() {
      if (disposed) {
        return;
      }
      disposed = true;
      workspaceEvents.dispose();
      views.dispose();
      source.dispose();
      preview.dispose();
      layout.dispose();
    },
  };
};
