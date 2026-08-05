import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import type { StudioBrand } from "../../shared/theme.tsx";
import type { PreviewDeck } from "../preview/deck.ts";
import type { ViewController } from "../views/controller.ts";
import type { LayoutController } from "../workspace/controller.ts";
import type { Surface } from "../workspace/schema.ts";

import { PopoutIcon } from "../../shared/ui/icons.tsx";
import { ViewMenu } from "../views/ViewMenu.tsx";
import { SURFACE_LABELS } from "../workspace/pane-actions.ts";
import { ModeNavigation } from "./ModeNavigation.tsx";
import { RuntimeMenu } from "./RuntimeMenu.tsx";
import { useToolbar } from "./useToolbar.ts";
import { WorkspaceMenu } from "./WorkspaceMenu.tsx";

interface ToolbarProps {
  bootstrap: StudioBootstrap;
  brand: StudioBrand;
  compact: boolean;
  compactSurfaces: readonly Surface[];
  layout: LayoutController;
  preview: PreviewDeck;
  views: ViewController;
}

export const Toolbar = (props: ToolbarProps) => {
  const model = useToolbar(props);
  const showCompactNavigation = model.compact && model.compactSurfaces.length > 1;
  return (
    <header className="studio-toolbar">
      <div className="studio-title">
        <span className="studio-brand-mark">
          <img className="studio-mark" src={model.brandMark} alt="" aria-hidden="true" />
        </span>
        <span className="studio-notebook">{model.notebookName}</span>
        <span className="studio-title-separator">/</span>
        <ViewMenu controller={props.views} />
      </div>

      <ModeNavigation active={model.mode} variant="primary" onSelect={model.actions.selectMode} />

      <div className="studio-controls">
        <RuntimeMenu
          current={model.runtime}
          runtimes={model.runtimes}
          status={model.status}
          visible={model.previewVisible}
          onSelect={model.actions.switchRuntime}
        />
        <a
          className="studio-control studio-icon-button studio-toolbar-action"
          href={model.previewState.url}
          target="_blank"
          rel="noopener"
          aria-label="Open preview in a new tab"
          hidden={!model.previewVisible}
        >
          <PopoutIcon />
        </a>
        <WorkspaceMenu
          arranging={model.arranging}
          mode={model.mode}
          previewUrl={model.previewState.url}
          previewVisible={model.previewVisible}
          runtime={model.runtime}
          runtimes={model.runtimes}
          status={model.status}
          onWorkspaceAction={model.actions.applyWorkspaceAction}
          onModeSelect={model.actions.selectMode}
          onRuntimeSelect={model.actions.switchRuntime}
        />
      </div>

      <nav
        className="studio-compact-tabs"
        aria-label="Studio surface"
        hidden={!showCompactNavigation}
      >
        {model.compactSurfaces.map((surface) => (
          <button
            key={surface}
            type="button"
            className="studio-control"
            aria-pressed={model.compactSurface === surface}
            onClick={() => model.actions.selectCompact(surface)}
          >
            {SURFACE_LABELS[surface]}
          </button>
        ))}
      </nav>

      <span className="studio-visually-hidden" data-state={model.status.state} role="status">
        {model.status.message}
      </span>
    </header>
  );
};
