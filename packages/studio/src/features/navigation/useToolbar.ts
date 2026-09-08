import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { useCallback } from "react";

import type { StudioBrand } from "../../shared/theme.tsx";
import type { PreviewDeck } from "../preview/deck.ts";
import type { ViewController } from "../views/controller.ts";
import type { LayoutController } from "../workspace/controller.ts";
import type { StudioMode, Surface } from "../workspace/schema.ts";

import { useStudioTheme } from "../../shared/theme.tsx";
import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { previewIsVisible } from "./model.ts";

export const useToolbar = ({
  bootstrap,
  brand,
  compact,
  compactSurfaces,
  layout,
  preview,
  views,
}: {
  bootstrap: StudioBootstrap;
  brand: StudioBrand;
  compact: boolean;
  compactSurfaces: readonly Surface[];
  layout: LayoutController;
  preview: PreviewDeck;
  views: ViewController;
}) => {
  const theme = useStudioTheme();
  const layoutSnapshot = useControllerSnapshot(layout);
  const previewSnapshot = useControllerSnapshot(preview);
  const viewSnapshot = useControllerSnapshot(views);
  const runtime = bootstrap.runtimes.find((candidate) => candidate.id === previewSnapshot.runtime);
  if (!runtime) {
    throw new Error(`Preview runtime ${JSON.stringify(previewSnapshot.runtime)} is unavailable`);
  }
  const previewState = previewSnapshot.states[runtime.id];
  const selectMode = useCallback(
    (mode: Exclude<StudioMode, "workspace">) => layout.selectMode(mode),
    [layout],
  );
  const selectCompact = useCallback((surface: Surface) => layout.selectCompact(surface), [layout]);
  const applyWorkspaceAction = useCallback(
    (action: Parameters<LayoutController["applyAction"]>[0]) => layout.applyAction(action),
    [layout],
  );
  const switchRuntime = useCallback(
    (runtime: string) => {
      if (views.getSnapshot().selecting === undefined) {
        preview.switchRuntime(runtime);
      }
    },
    [preview, views],
  );

  return {
    actions: { applyWorkspaceAction, selectCompact, selectMode, switchRuntime },
    arranging: layoutSnapshot.arranging,
    brandMark: brand.marks[theme],
    compact,
    compactSurface: layoutSnapshot.compact,
    compactSurfaces,
    mode: layoutSnapshot.mode,
    notebookName: bootstrap.notebook.name,
    previewState,
    previewVisible: previewIsVisible(compact, layoutSnapshot.compact, compactSurfaces),
    runtime,
    runtimeDisabled: viewSnapshot.selecting !== undefined,
    runtimes: bootstrap.runtimes,
    status:
      previewState.progress === null
        ? previewState.status
        : {
            ...previewState.status,
            message: previewState.progress.message,
            state: "loading" as const,
          },
  };
};
