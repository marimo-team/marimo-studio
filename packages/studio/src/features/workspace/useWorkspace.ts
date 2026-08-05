import {
  type Dispatch,
  type RefCallback,
  type SetStateAction,
  useCallback,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";

import type { PreviewDeck, PreviewDeckSnapshot } from "../preview/deck.ts";
import type { ViewController, ViewSnapshot } from "../views/controller.ts";
import type { LayoutController, LayoutSnapshot, PaneActionResult } from "./controller.ts";
import type { Axis, LayoutNode } from "./model.ts";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { workspaceGeometry, type WorkspaceGeometry } from "./geometry.ts";

interface WorkspaceSize {
  height: number;
  width: number;
}

export interface WorkspaceActions {
  arrangePane: (result: PaneActionResult) => void;
  cancelResize: () => void;
  commitResize: (tree: LayoutNode) => void;
  previewResize: (tree: LayoutNode) => void;
  setResizing: Dispatch<SetStateAction<Axis | null>>;
}

export interface WorkspaceModel {
  actions: WorkspaceActions;
  currentView: ViewSnapshot["current"];
  geometry: WorkspaceGeometry;
  layout: LayoutSnapshot;
  preview: PreviewDeckSnapshot;
  element: HTMLElement | null;
  ref: RefCallback<HTMLElement>;
  resizing: Axis | null;
}

const sameSize = (current: WorkspaceSize, width: number, height: number): boolean =>
  current.width === width && current.height === height;

export const useWorkspace = (
  controller: LayoutController,
  preview: PreviewDeck,
  views: ViewController,
): WorkspaceModel => {
  const workspaceSnapshot = useControllerSnapshot(controller);
  const previewSnapshot = useControllerSnapshot(preview);
  const viewSnapshot = useControllerSnapshot(views);
  const [element, setElement] = useState<HTMLElement | null>(null);
  const ref = useCallback((next: HTMLElement | null) => setElement(next), []);
  const [size, setSize] = useState<WorkspaceSize>({ width: 0, height: 0 });
  const [resizing, setResizing] = useState<Axis | null>(null);

  useLayoutEffect(() => {
    if (!element) {
      return;
    }
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      setSize((current) => {
        if (sameSize(current, width, height)) {
          return current;
        }
        return { width, height };
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);

  const geometry = useMemo(
    () =>
      workspaceGeometry(workspaceSnapshot.tree, workspaceSnapshot.compact, size.width, size.height),
    [workspaceSnapshot.compact, workspaceSnapshot.tree, size.height, size.width],
  );

  useLayoutEffect(() => {
    const frame = globalThis.requestAnimationFrame(() => preview.requestResize());
    return () => globalThis.cancelAnimationFrame(frame);
  }, [geometry.layout, preview]);

  const previewResize = useCallback((tree: LayoutNode) => controller.preview(tree), [controller]);
  const commitResize = useCallback((tree: LayoutNode) => controller.resize(tree), [controller]);
  const cancelResize = useCallback(() => controller.cancelPreview(), [controller]);
  const arrangePane = useCallback(
    (result: PaneActionResult) => controller.applyPaneAction(result),
    [controller],
  );

  return {
    element,
    ref,
    geometry,
    layout: workspaceSnapshot,
    preview: previewSnapshot,
    currentView: viewSnapshot.current,
    resizing,
    actions: { arrangePane, cancelResize, commitResize, previewResize, setResizing },
  };
};
