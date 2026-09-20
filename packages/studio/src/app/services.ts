import type { ActiveViewRequest } from "@marimo-studio/protocol/development-events";
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
import {
  type ActiveViewHandoffRemote,
  createActiveViewHandoffRemote,
  stageCommittedView,
} from "./active-view-handoff.ts";
import { bindEditorDocumentMutations } from "./editor-document-mutation.ts";
import { StudioRoutes } from "./routes.ts";
import { WorkspaceEventCoordinator } from "./workspace-event-coordinator.ts";

const CLOSE_RECONCILIATION_TIMEOUT_MS = 3_000;

export interface StudioServices {
  layout: LayoutController;
  preview: PreviewDeck;
  previewFrameIds: readonly string[];
  source: SourceController;
  views: ViewController;
  start(editor: HTMLIFrameElement, frames: ReadonlyMap<string, HTMLIFrameElement>): Promise<void>;
  close(): Promise<void>;
  dispose(): void;
}

export const createStudioServices = (
  bootstrap: StudioBootstrap,
  connectControlFrame?: ControlFrameConnector,
  initialActivation?: ActiveViewRequest,
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
  let activeViewHandoff: ActiveViewHandoffRemote;
  let views: ViewController | undefined;
  let started = false;
  const preview = new PreviewDeck({
    initialView: bootstrap.selectedView,
    initialRuntime: initialPreviewRuntime({
      available: runtimeIds,
      configured: bootstrap.defaultRuntime,
    }),
    initialNavigation: routes.currentNavigation(),
    runtimes: runtimeIds,
    viewUrl: routes.view,
    supportUrl: routes.support,
    syncQuery: routes.syncQuery,
    syncEditorQuery: (query, operationId, writeGeneration, signal) =>
      syncEditorQuery(
        routes.endpoint(bootstrap.urls.query),
        bootstrap.serverToken,
        bootstrap.clientId,
        query,
        operationId,
        writeGeneration,
        signal,
      ),
    navigate: async (view, navigation) =>
      (await views?.choose(view, "preserve", navigation)) ?? false,
    recordObservation: createBrowserObservationRemote(
      routes.support,
      bootstrap.serverToken,
      bootstrap.clientId,
    ),
    connectControlFrame,
  });
  const transition = new ViewTransition(bootstrap.selectedView, {
    prepare: async (_view, changed) => {
      preview.cancelNavigation();
      if (changed && !(await source.prepareViewChange())) {
        return false;
      }
      return true;
    },
    stage: (view, changed, navigation, signal, owner) => {
      const staged = preview.stageNavigation(
        view,
        changed,
        navigation,
        signal,
        owner === "agent" ? "document" : "rendered",
      );
      const fromView = views?.getSnapshot().current ?? bootstrap.selectedView;
      return stageCommittedView(
        staged,
        started && changed && owner === "browser"
          ? () => activeViewHandoff.stage(fromView, view, signal)
          : undefined,
      );
    },
    commit: (view, landing, changed, navigation) => {
      if (navigation) {
        routes.syncQuery(navigation.query);
      }
      layout.switchView(view, landing);
      if (changed) {
        source.selectView(view);
      } else if (navigation) {
        preview.navigateWithinView(navigation);
      }
      const studioUrl = new URL(routes.studio(view));
      studioUrl.hash = navigation?.hash ?? "";
      globalThis.history.replaceState({}, "", studioUrl);
      if (landing === "authoring") {
        source.focusSource();
      }
      return true;
    },
    cancel: () => {
      preview.cancelNavigation();
    },
  });
  views = new ViewController(
    bootstrap.selectedView,
    [...bootstrap.views],
    createViewRemote(routes.endpoint(bootstrap.urls.views), bootstrap.serverToken),
    (view, landing, navigation, signal, owner) =>
      transition.select(view, landing, navigation, signal, owner),
    () => source.prepareViewChange(),
    () => transition.cancel(),
    [],
    "",
    (view) => preview.prepareViewDeletion(view),
    (view) => preview.releaseView(view),
    bootstrap.defaultView,
    (view) => {
      preview.replaceView(view);
      source.replaceView(view);
    },
  );
  const workspaceEvents = new WorkspaceEventCoordinator({
    eventsUrl: routes.endpoint(bootstrap.urls.events),
    views,
    preview,
    source,
    acknowledge: createViewActivationRemote(
      routes.endpoint(bootstrap.urls.agent),
      bootstrap.serverToken,
      bootstrap.clientId,
    ),
  });
  activeViewHandoff = createActiveViewHandoffRemote(
    routes.endpoint(bootstrap.urls.agent),
    bootstrap.serverToken,
    bootstrap.clientId,
    (view, signal) => workspaceEvents.recoverActiveView(view, signal),
  );
  let disposed = false;
  let finished = false;
  let closing: Promise<void> | undefined;
  let stopEditorDocumentMutations: (() => void) | undefined;

  const finishClose = () => {
    if (finished) {
      return;
    }
    finished = true;
    stopEditorDocumentMutations?.();
    stopEditorDocumentMutations = undefined;
    workspaceEvents.dispose();
    activeViewHandoff.dispose();
    source.dispose();
    preview.dispose();
    layout.dispose();
  };

  const close = (): Promise<void> => {
    if (closing) {
      return closing;
    }
    disposed = true;
    started = false;
    const rollback = transition.close();
    views.dispose();
    if (!rollback) {
      finishClose();
      closing = Promise.resolve();
      return closing;
    }
    const rollbackFinished = rollback.catch(() => undefined);
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let settleDeadline: (result: "cancelled" | "timeout") => void = () => {};
    const forceDisconnect = new Promise<"cancelled" | "timeout">((resolve) => {
      settleDeadline = resolve;
      deadline = setTimeout(() => resolve("timeout"), CLOSE_RECONCILIATION_TIMEOUT_MS);
    }).then((result) => {
      if (result === "timeout") {
        workspaceEvents.dispose();
        activeViewHandoff.dispose();
        finishClose();
      }
    });
    closing = Promise.race([rollbackFinished, forceDisconnect]).finally(() => {
      if (deadline !== undefined) {
        clearTimeout(deadline);
      }
      settleDeadline("cancelled");
      finishClose();
    });
    return closing;
  };

  return {
    layout,
    preview,
    previewFrameIds: preview.frameIds,
    source,
    views,
    async start(editor, frames) {
      started = true;
      preview.attach(editor, frames);
      stopEditorDocumentMutations = bindEditorDocumentMutations(editor, {
        pending: (generation, acknowledgement) =>
          preview.notebookMutationPending(generation, acknowledgement),
        reloaded: () => {
          if (preview.editorDocumentReloaded()) {
            workspaceEvents.reconcileEditorReload();
          }
        },
        saved: (generation, succeeded) => {
          if (!succeeded) {
            preview.notebookMutationSaveFailed(generation);
          } else if (preview.notebookMutationSaved(generation)) {
            workspaceEvents.reconcileNotebookMutation(generation);
          }
        },
        transactionApplied: (generation, changed) =>
          preview.notebookMutationTransactionApplied(generation, changed),
        transactionFailed: (generation) => preview.notebookMutationTransactionFailed(generation),
      });
      void views.ensureStarterCatalog();
      workspaceEvents.start(initialActivation);
      await source.start();
    },
    close,
    dispose() {
      if (disposed) {
        return;
      }
      void close().catch(() => undefined);
    },
  };
};
