import type { Axis, DividerRectangle } from "./model.ts";

interface PointerCoordinates {
  clientX: number;
  clientY: number;
}

interface DividerAxisModel {
  coordinate(event: PointerCoordinates): number;
  label: string;
  orientation: "horizontal" | "vertical";
  origin(workspace: DOMRect, divider: DividerRectangle): number;
  size(divider: DividerRectangle): number;
}

export const DIVIDER_AXES = {
  x: {
    coordinate: (event) => event.clientX,
    label: "Resize columns",
    orientation: "vertical",
    origin: (workspace, divider) => workspace.left + divider.bounds.left,
    size: (divider) => divider.bounds.width - divider.width,
  },
  y: {
    coordinate: (event) => event.clientY,
    label: "Resize rows",
    orientation: "horizontal",
    origin: (workspace, divider) => workspace.top + divider.bounds.top,
    size: (divider) => divider.bounds.height - divider.height,
  },
} as const satisfies Readonly<Record<Axis, DividerAxisModel>>;

export const dividerStyle = (divider: DividerRectangle) => ({
  height: divider.height,
  left: divider.left,
  top: divider.top,
  width: divider.width,
});

const keyboardDirection = (axis: Axis, key: string): -1 | 1 | undefined => {
  switch (key) {
    case "ArrowDown":
      return axis === "y" ? 1 : undefined;
    case "ArrowLeft":
      return axis === "x" ? -1 : undefined;
    case "ArrowRight":
      return axis === "x" ? 1 : undefined;
    case "ArrowUp":
      return axis === "y" ? -1 : undefined;
    default:
      return undefined;
  }
};

export const keyboardRatio = (
  divider: DividerRectangle,
  key: string,
  step: number,
): number | undefined => {
  const direction = keyboardDirection(divider.axis, key);
  if (direction === undefined) {
    return undefined;
  }
  return divider.ratio + direction * step;
};
