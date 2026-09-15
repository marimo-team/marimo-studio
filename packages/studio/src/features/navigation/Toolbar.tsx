import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { CodeIcon, Columns2Icon } from "lucide-react";

import type { StudioBrand } from "../../shared/theme.tsx";
import type { PreviewDeck } from "../preview/deck.ts";
import type { ViewController } from "../views/controller.ts";
import type { LayoutController } from "../workspace/controller.ts";
import type { Surface } from "../workspace/schema.ts";

import { standaloneViewUrl } from "../../shared/standaloneViewUrl.ts";
import { ViewMenu } from "../views/ViewMenu.tsx";
import { SURFACE_LABELS } from "../workspace/pane-actions.ts";
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
  return (
    <header className="studio-toolbar" aria-label="Studio">
      <div className="studio-title">
        <span className="studio-notebook">{model.notebookName}</span>
        <span className="studio-title-separator">/</span>
        <ViewMenu controller={props.views} />
      </div>
      <div className="studio-controls">
        <button
          type="button"
          className="studio-control studio-icon-button"
          aria-label="Show notebook beside view"
          aria-pressed={model.notebookVisible}
          title="Show notebook beside view"
          onClick={() => props.layout.toggleNotebook()}
        >
          <Columns2Icon className="studio-mode-icon" aria-hidden />
        </button>
        <button
          type="button"
          className="studio-control studio-icon-button studio-source-toggle"
          aria-label="Toggle Source editor"
          aria-pressed={model.sourceVisible}
          title={model.sourceVisible ? "Hide Source editor" : "Edit view source"}
          onClick={model.actions.toggleSource}
        >
          <CodeIcon className="studio-mode-icon" aria-hidden />
        </button>
        {model.compact && model.compactSurfaces.length > 1 ? (
          <select
            className="studio-compact-surface studio-control"
            aria-label="Visible surface"
            value={model.compactSurface}
            onChange={(event) => {
              const surface = model.compactSurfaces.find(
                (candidate) => candidate === event.target.value,
              );
              if (surface) model.actions.selectCompact(surface);
            }}
          >
            {model.compactSurfaces.map((surface) => (
              <option key={surface} value={surface}>
                {SURFACE_LABELS[surface]}
              </option>
            ))}
          </select>
        ) : null}
      </div>
      <RuntimeMenu
        current={model.runtime}
        disabled={model.runtimeDisabled}
        runtimes={model.runtimes}
        status={model.status}
        visible
        view={model.currentView}
        onSelect={model.actions.switchRuntime}
      />
      <WorkspaceMenu
        arranging={model.arranging}
        mode={model.mode}
        previewUrl={standaloneViewUrl(model.previewState.url)}
        previewVisible={model.previewVisible}
        onWorkspaceAction={model.actions.applyWorkspaceAction}
        onModeSelect={model.actions.selectMode}
      />
      <span
        className="studio-visually-hidden"
        data-state={model.status.state}
        role="status"
        aria-label="View status"
      >
        {model.status.message}
      </span>
    </header>
  );
};
