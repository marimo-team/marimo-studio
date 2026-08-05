import type { Axis, DividerRectangle } from "./model.ts";

interface PointerCoordinates {
  clientX: number;
  clientY: number;
}

interface DividerAxisModel {
  coordinate(event: PointerCoordinates): number;
  keys: Readonly<Record<string, number>>;
  label: string;
  orientation: "horizontal" | "vertical";
  origin(workspace: DOMRect, divider: DividerRectangle): number;
  size(divider: DividerRectangle): number;
}

export const DIVIDER_AXES: Readonly<Record<Axis, DividerAxisModel>> = {
  x: {
    coordinate: (event) => event.clientX,
    keys: { ArrowLeft: -1, ArrowRight: 1 },
    label: "Resize columns",
    orientation: "vertical",
    origin: (workspace, divider) => workspace.left + divider.bounds.left,
    size: (divider) => divider.bounds.width - divider.width,
  },
  y: {
    coordinate: (event) => event.clientY,
    keys: { ArrowDown: 1, ArrowUp: -1 },
    label: "Resize rows",
    orientation: "horizontal",
    origin: (workspace, divider) => workspace.top + divider.bounds.top,
    size: (divider) => divider.bounds.height - divider.height,
  },
};

export const dividerStyle = (divider: DividerRectangle) => ({
  height: divider.height,
  left: divider.left,
  top: divider.top,
  width: divider.width,
});

export const keyboardRatio = (
  divider: DividerRectangle,
  key: string,
  step: number,
): number | undefined => {
  const direction = DIVIDER_AXES[divider.axis].keys[key];
  if (direction === undefined) {
    return undefined;
  }
  return divider.ratio + direction * step;
};
