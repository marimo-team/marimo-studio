import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import {
  Columns3Icon,
  LayoutTemplateIcon,
  MoveIcon,
  RotateCcwIcon,
  type LucideIcon,
} from "lucide-react";

import type { PreviewStatus } from "../preview/status.ts";
import type { StudioMode } from "../workspace/schema.ts";

import { MoreIcon, PopoutIcon } from "../../shared/ui/icons.tsx";
import { closeParentMenu } from "./menu.ts";
import { type WorkspaceAction, WORKSPACE_ACTION_GROUPS } from "./model.ts";
import { ModeNavigation } from "./ModeNavigation.tsx";
import { RuntimeOptions } from "./RuntimeOptions.tsx";

const WORKSPACE_ACTION_ICONS: Readonly<Record<WorkspaceAction, LucideIcon>> = {
  arrange: MoveIcon,
  equalize: Columns3Icon,
  reset: RotateCcwIcon,
  workspace: LayoutTemplateIcon,
};

export const WorkspaceMenu = ({
  arranging,
  mode,
  previewUrl,
  previewVisible,
  runtime,
  runtimes,
  status,
  onWorkspaceAction,
  onModeSelect,
  onRuntimeSelect,
}: {
  arranging: boolean;
  mode: StudioMode;
  previewUrl: string;
  previewVisible: boolean;
  runtime: StudioRuntime;
  runtimes: readonly StudioRuntime[];
  status: PreviewStatus;
  onWorkspaceAction: (action: WorkspaceAction) => void;
  onModeSelect: (mode: Exclude<StudioMode, "workspace">) => void;
  onRuntimeSelect: (runtime: string) => void;
}) => (
  <details
    className="studio-menu studio-workspace-menu"
    data-active={mode === "workspace" || undefined}
    data-arranging={arranging || undefined}
  >
    <summary
      className="studio-control studio-menu-trigger studio-icon-button studio-toolbar-action"
      aria-label="Workspace options"
    >
      <MoreIcon />
    </summary>
    <div className="studio-menu-popover studio-workspace-popover">
      <div className="studio-overflow-preview" hidden={!previewVisible}>
        <strong className="studio-menu-heading">Preview runtime</strong>
        <div className="studio-overflow-runtime-status" data-state={status.state}>
          <span className="studio-runtime-dot" aria-hidden="true" />
          <span>{status.message}</span>
        </div>
        <RuntimeOptions current={runtime.id} runtimes={runtimes} onSelect={onRuntimeSelect} />
        <a
          className="studio-menu-item studio-overflow-popout"
          href={previewUrl}
          target="_blank"
          rel="noopener"
        >
          <PopoutIcon />
          <span>Open preview in new tab</span>
        </a>
        <div className="studio-menu-separator" />
      </div>
      <strong className="studio-menu-heading">Show</strong>
      <ModeNavigation active={mode} variant="overflow" onSelect={onModeSelect} />
      <strong className="studio-menu-heading">Workspace</strong>
      {WORKSPACE_ACTION_GROUPS.map((group, index) => (
        <div key={group[0].action} className="studio-menu-action-group">
          {index > 0 ? <div className="studio-menu-separator" /> : null}
          {group.map((item) => {
            const Icon = WORKSPACE_ACTION_ICONS[item.action];
            return (
              <button
                key={item.action}
                type="button"
                className="studio-menu-item"
                aria-current={
                  item.action === "workspace" && mode === "workspace" ? "true" : undefined
                }
                aria-pressed={item.action === "arrange" ? arranging : undefined}
                onClick={(event) => {
                  onWorkspaceAction(item.action);
                  closeParentMenu(event.currentTarget);
                }}
              >
                <Icon className="studio-menu-item-icon" aria-hidden />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  </details>
);
