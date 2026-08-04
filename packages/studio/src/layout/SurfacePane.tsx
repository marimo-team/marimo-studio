import type { ReactNode } from "react";

import type { PaneActionResult } from "./controller.ts";
import type { LayoutNode, Rectangle, Surface } from "./model.ts";

import { paneStyle } from "./geometry.ts";
import { PaneMenu } from "./PaneMenu.tsx";

export const SurfacePane = ({
  arranging,
  children,
  label,
  rectangle,
  surface,
  tree,
  onArrange,
}: {
  arranging: boolean;
  children: ReactNode;
  label: string;
  rectangle?: Rectangle;
  surface: Surface;
  tree: LayoutNode;
  onArrange: (result: PaneActionResult) => void;
}) => {
  const hidden = rectangle === undefined;
  return (
    <section
      className="studio-pane"
      aria-label={label}
      hidden={hidden}
      inert={hidden}
      style={paneStyle(rectangle)}
    >
      <div className="studio-arrange-chrome">
        <strong>{label}</strong>
        <PaneMenu target={surface} tree={tree} onApply={onArrange} />
      </div>
      {children}
      {arranging ? (
        <span className="studio-visually-hidden">Pane arrangement is active</span>
      ) : null}
    </section>
  );
};
