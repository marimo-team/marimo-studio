import type { DividerRectangle, LayoutNode } from "./model.ts";

import { DIVIDER_AXES, dividerStyle } from "./divider-model.ts";
import { useDivider } from "./useDivider.ts";

interface DividerProps {
  divider: DividerRectangle;
  tree: LayoutNode;
  workspace: HTMLElement | null;
  onPreview: (tree: LayoutNode) => void;
  onCommit: (tree: LayoutNode) => void;
  onCancel: () => void;
  onResize: (axis: "x" | "y" | null) => void;
}

export const Divider = ({
  divider,
  tree,
  workspace,
  onPreview,
  onCommit,
  onCancel,
  onResize,
}: DividerProps) => {
  const axis = DIVIDER_AXES[divider.axis];
  const interactions = useDivider({
    divider,
    tree,
    workspace,
    onPreview,
    onCommit,
    onCancel,
    onResize,
  });

  return (
    <div
      className="studio-divider"
      role="separator"
      tabIndex={0}
      data-axis={divider.axis}
      aria-orientation={axis.orientation}
      aria-label={axis.label}
      aria-valuemin={10}
      aria-valuemax={90}
      aria-valuenow={Math.round(divider.ratio * 100)}
      style={dividerStyle(divider)}
      onPointerDown={interactions.start}
      onPointerMove={interactions.move}
      onPointerUp={(event) => interactions.finish(true, event.pointerId)}
      onPointerCancel={(event) => interactions.finish(false, event.pointerId)}
      onLostPointerCapture={(event) => interactions.finish(false, event.pointerId)}
      onDoubleClick={interactions.reset}
      onKeyDown={interactions.keyDown}
    />
  );
};
