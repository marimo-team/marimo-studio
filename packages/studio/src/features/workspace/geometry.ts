import {
  type ComputedLayout,
  computeLayout,
  type LayoutNode,
  needsCompactLayout,
  type Rectangle,
  type Surface,
  visibleSurfaces,
} from "./model.ts";

export interface WorkspaceGeometry {
  compact: boolean;
  layout: ComputedLayout;
  surfaces: readonly Surface[];
}

const emptyLayout = (): ComputedLayout => ({
  panes: new Map<Surface, Rectangle>(),
  dividers: [],
});

const visibleLayout = (
  tree: LayoutNode,
  bounds: Rectangle,
  active: Surface | null,
): ComputedLayout => {
  if (active) {
    return { panes: new Map<Surface, Rectangle>([[active, bounds]]), dividers: [] };
  }
  return computeLayout(tree, bounds);
};

export const workspaceGeometry = (
  tree: LayoutNode,
  compactSurface: Surface,
  width: number,
  height: number,
): WorkspaceGeometry => {
  const surfaces = visibleSurfaces(tree);
  if (width <= 0 || height <= 0) {
    return { compact: false, surfaces, layout: emptyLayout() };
  }

  const bounds = { left: 0, top: 0, width, height };
  const compact = needsCompactLayout(tree, bounds);
  const active = compact ? compactSurface : null;
  return {
    compact,
    surfaces,
    layout: visibleLayout(tree, bounds, active),
  };
};

export const paneStyle = (rectangle: Rectangle | undefined) => {
  if (!rectangle) {
    return undefined;
  }
  return {
    left: rectangle.left,
    top: rectangle.top,
    width: rectangle.width,
    height: rectangle.height,
  };
};
