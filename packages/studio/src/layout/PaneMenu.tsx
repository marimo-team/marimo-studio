import type { PaneActionResult } from "./controller.ts";
import type { LayoutNode, Surface } from "./model.ts";

import { MenuChevron } from "../components/icons.tsx";
import { PLACEMENTS, SURFACE_LABELS } from "./pane-actions.ts";
import { usePaneMenu } from "./usePaneMenu.ts";

interface PaneMenuProps {
  target: Surface;
  tree: LayoutNode;
  onApply: (result: PaneActionResult) => void;
}

export const PaneMenu = ({ target, tree, onApply }: PaneMenuProps) => {
  const model = usePaneMenu(target, tree, onApply);
  const arrangeSection =
    model.peers.length > 0 ? (
      <>
        {model.missing.length > 0 ? <div className="studio-menu-separator" /> : null}
        <strong className="studio-menu-heading">Arrange</strong>
        {model.peers.map((surface) => (
          <button
            key={surface}
            type="button"
            className="studio-menu-item"
            onClick={() => model.actions.swap(surface)}
          >
            Swap with {SURFACE_LABELS[surface]}
          </button>
        ))}
        <div className="studio-menu-separator" />
        <button type="button" className="studio-menu-item" onClick={model.actions.close}>
          Close pane
        </button>
      </>
    ) : null;

  return (
    <details ref={model.menu} className="studio-pane-menu">
      <summary className="studio-pane-menu-trigger" aria-label={`Arrange ${target} pane`}>
        <span className="studio-pane-menu-label">Arrange</span>
        <MenuChevron />
      </summary>
      <div className="studio-menu-popover studio-pane-popover">
        {model.missing.map((surface, index) => (
          <div key={surface} className="studio-pane-action-section">
            {index > 0 ? <div className="studio-menu-separator" /> : null}
            <strong className="studio-menu-heading">Add {SURFACE_LABELS[surface]}</strong>
            <div className="studio-placement-grid">
              {PLACEMENTS.map((placement) => (
                <button
                  key={placement.value}
                  type="button"
                  className="studio-menu-item studio-placement-action"
                  data-placement={placement.value}
                  aria-label={`Add ${SURFACE_LABELS[surface]} ${placement.relation} ${SURFACE_LABELS[target]}`}
                  onClick={() => model.actions.add(surface, placement.value)}
                >
                  <span
                    className="studio-placement-icon"
                    data-placement={placement.value}
                    aria-hidden="true"
                  />
                  <span>{placement.label}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {arrangeSection}
      </div>
    </details>
  );
};
