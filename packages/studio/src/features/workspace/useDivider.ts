import { type KeyboardEvent, type PointerEvent, useCallback, useEffect, useRef } from "react";

import type { DividerRectangle, LayoutNode } from "./model.ts";

import { DIVIDER_AXES, keyboardRatio } from "./divider-model.ts";
import { updateRatio } from "./model.ts";

interface DividerInteractions {
  onCancel: () => void;
  onCommit: (tree: LayoutNode) => void;
  onPreview: (tree: LayoutNode) => void;
  onResize: (axis: "x" | "y" | null) => void;
}

interface DividerOptions extends DividerInteractions {
  divider: DividerRectangle;
  tree: LayoutNode;
  workspace: HTMLElement | null;
}

interface DragState {
  frame?: number;
  origin: number;
  pointerId: number;
  ratio: number;
  size: number;
  tree: LayoutNode;
}

const cancelFrame = (drag: DragState): void => {
  if (drag.frame !== undefined) {
    globalThis.cancelAnimationFrame(drag.frame);
  }
};

export const useDivider = ({
  divider,
  tree,
  workspace,
  onPreview,
  onCommit,
  onCancel,
  onResize,
}: DividerOptions) => {
  const drag = useRef<DragState | undefined>(undefined);
  const axis = DIVIDER_AXES[divider.axis];

  useEffect(
    () => () => {
      const current = drag.current;
      if (!current) {
        return;
      }
      cancelFrame(current);
      drag.current = undefined;
      onResize(null);
      onCancel();
    },
    [onCancel, onResize],
  );

  const start = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      if (!workspace) {
        return;
      }
      drag.current = {
        pointerId: event.pointerId,
        origin: axis.origin(workspace.getBoundingClientRect(), divider),
        size: axis.size(divider),
        ratio: divider.ratio,
        tree,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      onResize(divider.axis);
    },
    [axis, divider, onResize, tree, workspace],
  );

  const move = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const current = drag.current;
      if (!current || current.pointerId !== event.pointerId) {
        return;
      }
      current.ratio = (axis.coordinate(event) - current.origin) / current.size;
      if (current.frame !== undefined) {
        return;
      }
      current.frame = globalThis.requestAnimationFrame(() => {
        current.frame = undefined;
        onPreview(updateRatio(current.tree, divider.id, current.ratio));
      });
    },
    [axis, divider.id, onPreview],
  );

  const finish = useCallback(
    (save: boolean, pointerId: number) => {
      const current = drag.current;
      if (!current || current.pointerId !== pointerId) {
        return;
      }
      cancelFrame(current);
      drag.current = undefined;
      onResize(null);
      if (save) {
        onCommit(updateRatio(current.tree, divider.id, current.ratio));
        return;
      }
      onCancel();
    },
    [divider.id, onCancel, onCommit, onResize],
  );

  const keyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const ratio = keyboardRatio(divider, event.key, event.shiftKey ? 0.1 : 0.02);
      if (ratio === undefined) {
        return;
      }
      event.preventDefault();
      onCommit(updateRatio(tree, divider.id, ratio));
    },
    [divider, onCommit, tree],
  );

  const reset = useCallback(
    () => onCommit(updateRatio(tree, divider.id, 0.5)),
    [divider.id, onCommit, tree],
  );

  return { finish, keyDown, move, reset, start };
};
