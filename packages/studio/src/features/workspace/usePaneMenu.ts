import { useCallback, useMemo, useRef } from "react";

import type { PaneActionResult } from "./controller.ts";
import type { LayoutNode, Placement, Surface } from "./model.ts";

import { closeSurface, splitSurface, swapSurfaces, visibleSurfaces } from "./model.ts";
import { SURFACES } from "./pane-actions.ts";

interface PaneMenuActions {
  add: (surface: Surface, placement: Placement) => void;
  close: () => void;
  move: (surface: Surface, placement: Placement) => void;
  swap: (surface: Surface) => void;
}

export const usePaneMenu = (
  target: Surface,
  tree: LayoutNode,
  onApply: (result: PaneActionResult) => void,
) => {
  const menu = useRef<HTMLDetailsElement>(null);
  const { missing, peers } = useMemo(() => {
    const visible = visibleSurfaces(tree);
    return {
      missing: SURFACES.filter((surface) => !visible.includes(surface)),
      peers: visible.filter((surface) => surface !== target),
    };
  }, [target, tree]);
  const apply = useCallback(
    (result: PaneActionResult) => {
      onApply(result);
      menu.current?.removeAttribute("open");
    },
    [onApply],
  );
  const actions: PaneMenuActions = useMemo(
    () => ({
      add: (surface, placement) =>
        apply({ tree: splitSurface(tree, target, surface, placement), compact: surface }),
      move: (surface, placement) =>
        apply({ tree: splitSurface(tree, surface, target, placement), compact: target }),
      close: () => apply({ tree: closeSurface(tree, target) }),
      swap: (surface) => apply({ tree: swapSurfaces(tree, target, surface) }),
    }),
    [apply, target, tree],
  );
  return { actions, menu, missing, peers };
};
