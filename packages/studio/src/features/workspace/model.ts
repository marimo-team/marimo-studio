import {
  decodeLayout,
  type Axis,
  type LayoutNode,
  type PaneNode,
  type SplitNode,
  type StudioMode,
  type Surface,
} from "./schema.ts";

export type { Axis, LayoutNode, PaneNode, SplitNode, StudioMode, Surface } from "./schema.ts";

export type Placement = "left" | "right" | "above" | "below";

export interface Rectangle {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface DividerRectangle extends Rectangle {
  id: string;
  axis: Axis;
  ratio: number;
  bounds: Rectangle;
}

export interface ComputedLayout {
  panes: Map<Surface, Rectangle>;
  dividers: DividerRectangle[];
}

const DIVIDER_SIZE = 5;

interface MinimumSize {
  width: number;
  height: number;
}

const MINIMUM = {
  notebook: { width: 320, height: 220 },
  source: { width: 280, height: 220 },
  preview: { width: 280, height: 220 },
} satisfies Record<Surface, MinimumSize>;

const PLACEMENT_LAYOUT = {
  left: { axis: "x", addedFirst: true },
  right: { axis: "x", addedFirst: false },
  above: { axis: "y", addedFirst: true },
  below: { axis: "y", addedFirst: false },
} satisfies Record<Placement, { axis: Axis; addedFirst: boolean }>;

const pane = (surface: Surface): PaneNode => ({
  type: "pane",
  id: `pane-${surface}`,
  surface,
});

const split = (
  id: string,
  axis: Axis,
  first: LayoutNode,
  second: LayoutNode,
  ratio = 0.5,
): SplitNode => ({ type: "split", id, axis, ratio, first, second });

export const notebookLayout = (): LayoutNode => pane("notebook");

export const previewLayout = (): LayoutNode => pane("preview");

export const sourceLayout = (): LayoutNode =>
  split("source-preview", "x", pane("source"), pane("preview"));

const threeSurfaceLayout = (): LayoutNode =>
  split(
    "notebook-authoring",
    "x",
    pane("notebook"),
    split("source-preview", "y", pane("source"), pane("preview")),
  );

export const developLayout = (): LayoutNode => threeSurfaceLayout();

export const layoutForMode = (
  mode: StudioMode,
  source: LayoutNode,
  workspace: LayoutNode,
): LayoutNode => {
  switch (mode) {
    case "develop":
      return developLayout();
    case "notebook":
      return notebookLayout();
    case "preview":
      return previewLayout();
    case "source":
      return source;
    case "workspace":
      return workspace;
  }
};

export const visibleSurfaces = (node: LayoutNode): Surface[] => {
  if (node.type === "pane") {
    return [node.surface];
  }
  return [...visibleSurfaces(node.first), ...visibleSurfaces(node.second)];
};

const minimumSize = (node: LayoutNode): MinimumSize => {
  if (node.type === "pane") {
    return MINIMUM[node.surface];
  }
  const first = minimumSize(node.first);
  const second = minimumSize(node.second);
  if (node.axis === "x") {
    return {
      width: first.width + second.width + DIVIDER_SIZE,
      height: Math.max(first.height, second.height),
    };
  }
  return {
    width: Math.max(first.width, second.width),
    height: first.height + second.height + DIVIDER_SIZE,
  };
};

export const needsCompactLayout = (node: LayoutNode, bounds: Rectangle): boolean => {
  const minimum = minimumSize(node);
  return bounds.width < minimum.width || bounds.height < minimum.height;
};

const constrainRatio = (node: SplitNode, bounds: Rectangle): number => {
  const available = Math.max(1, (node.axis === "x" ? bounds.width : bounds.height) - DIVIDER_SIZE);
  const first = minimumSize(node.first);
  const second = minimumSize(node.second);
  const firstMinimum = node.axis === "x" ? first.width : first.height;
  const secondMinimum = node.axis === "x" ? second.width : second.height;
  const lower = Math.min(0.5, firstMinimum / available);
  const upper = Math.max(0.5, 1 - secondMinimum / available);
  return Math.min(upper, Math.max(lower, node.ratio));
};

export const computeLayout = (node: LayoutNode, bounds: Rectangle): ComputedLayout => {
  const result: ComputedLayout = { panes: new Map(), dividers: [] };
  const visit = (current: LayoutNode, rectangle: Rectangle): void => {
    if (current.type === "pane") {
      result.panes.set(current.surface, rectangle);
      return;
    }
    const ratio = constrainRatio(current, rectangle);
    if (current.axis === "x") {
      const available = rectangle.width - DIVIDER_SIZE;
      const firstWidth = available * ratio;
      const secondLeft = rectangle.left + firstWidth + DIVIDER_SIZE;
      visit(current.first, { ...rectangle, width: firstWidth });
      visit(current.second, {
        ...rectangle,
        left: secondLeft,
        width: rectangle.left + rectangle.width - secondLeft,
      });
      result.dividers.push({
        id: current.id,
        axis: current.axis,
        ratio,
        bounds: rectangle,
        left: rectangle.left + firstWidth,
        top: rectangle.top,
        width: DIVIDER_SIZE,
        height: rectangle.height,
      });
      return;
    }
    const available = rectangle.height - DIVIDER_SIZE;
    const firstHeight = available * ratio;
    const secondTop = rectangle.top + firstHeight + DIVIDER_SIZE;
    visit(current.first, { ...rectangle, height: firstHeight });
    visit(current.second, {
      ...rectangle,
      top: secondTop,
      height: rectangle.top + rectangle.height - secondTop,
    });
    result.dividers.push({
      id: current.id,
      axis: current.axis,
      ratio,
      bounds: rectangle,
      left: rectangle.left,
      top: rectangle.top + firstHeight,
      width: rectangle.width,
      height: DIVIDER_SIZE,
    });
  };
  visit(node, bounds);
  return result;
};

export const updateRatio = (node: LayoutNode, id: string, ratio: number): LayoutNode => {
  if (node.type === "pane") {
    return node;
  }
  if (node.id === id) {
    return { ...node, ratio: Math.min(0.9, Math.max(0.1, ratio)) };
  }
  return {
    ...node,
    first: updateRatio(node.first, id, ratio),
    second: updateRatio(node.second, id, ratio),
  };
};

export const equalizeLayout = (node: LayoutNode): LayoutNode => {
  if (node.type === "pane") {
    return node;
  }
  return {
    ...node,
    ratio: 0.5,
    first: equalizeLayout(node.first),
    second: equalizeLayout(node.second),
  };
};

const removeSurface = (node: LayoutNode, surface: Surface): LayoutNode | null => {
  if (node.type === "pane") {
    return node.surface === surface ? null : node;
  }
  const first = removeSurface(node.first, surface);
  const second = removeSurface(node.second, surface);
  if (first === null) {
    return second;
  }
  if (second === null) {
    return first;
  }
  return { ...node, first, second };
};

export const closeSurface = (node: LayoutNode, surface: Surface): LayoutNode =>
  removeSurface(node, surface) ?? node;

const replacePane = (node: LayoutNode, surface: Surface, replacement: LayoutNode): LayoutNode => {
  if (node.type === "pane") {
    return node.surface === surface ? replacement : node;
  }
  return {
    ...node,
    first: replacePane(node.first, surface, replacement),
    second: replacePane(node.second, surface, replacement),
  };
};

const nextCustomSplitId = (node: LayoutNode): string => {
  const ids = new Set<string>();
  const visit = (current: LayoutNode) => {
    ids.add(current.id);
    if (current.type === "split") {
      visit(current.first);
      visit(current.second);
    }
  };
  visit(node);
  let index = 1;
  while (ids.has(`custom-${index}`)) {
    index += 1;
  }
  return `custom-${index}`;
};

export const splitSurface = (
  node: LayoutNode,
  target: Surface,
  added: Surface,
  placement: Placement,
): LayoutNode => {
  if (target === added || !visibleSurfaces(node).includes(target)) {
    return node;
  }
  const withoutAdded = removeSurface(node, added) ?? node;
  const { axis, addedFirst } = PLACEMENT_LAYOUT[placement];
  const surfaces = addedFirst ? [added, target] : [target, added];
  return replacePane(
    withoutAdded,
    target,
    split(nextCustomSplitId(withoutAdded), axis, pane(surfaces[0]), pane(surfaces[1])),
  );
};

export const swapSurfaces = (node: LayoutNode, first: Surface, second: Surface): LayoutNode => {
  if (first === second) {
    return node;
  }
  const replacements = new Map<Surface, Surface>([
    [first, second],
    [second, first],
  ]);
  const visit = (current: LayoutNode): LayoutNode => {
    if (current.type === "pane") {
      return pane(replacements.get(current.surface) ?? current.surface);
    }
    return {
      ...current,
      first: visit(current.first),
      second: visit(current.second),
    };
  };
  return visit(node);
};

export const parseLayout = (value: string | null): LayoutNode | null => {
  if (!value) {
    return null;
  }
  return decodeLayout(value);
};
