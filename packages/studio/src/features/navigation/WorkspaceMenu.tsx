import {
  Columns3Icon,
  LayoutTemplateIcon,
  MoveIcon,
  RotateCcwIcon,
  type LucideIcon,
} from "lucide-react";

import type { StudioMode } from "../workspace/schema.ts";

import { MoreIcon, PopoutIcon } from "../../shared/ui/icons.tsx";
import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";
import { closeParentMenu } from "./menu.ts";
import { type WorkspaceAction, WORKSPACE_ACTION_GROUPS } from "./model.ts";
import { ModeNavigation } from "./ModeNavigation.tsx";

const WORKSPACE_ACTION_ICONS = {
  arrange: MoveIcon,
  equalize: Columns3Icon,
  reset: RotateCcwIcon,
  workspace: LayoutTemplateIcon,
} as const satisfies Readonly<Record<WorkspaceAction, LucideIcon>>;

export const WorkspaceMenu = ({
  arranging,
  mode,
  previewUrl,
  previewVisible,
  onWorkspaceAction,
  onModeSelect,
}: {
  arranging: boolean;
  mode: StudioMode;
  previewUrl: string;
  previewVisible: boolean;
  onWorkspaceAction: (action: WorkspaceAction) => void;
  onModeSelect: (mode: Exclude<StudioMode, "workspace">) => void;
}) => {
  const menu = useDisclosureMenu();
  return (
    <details
      ref={menu.detailsRef}
      className="studio-menu studio-workspace-menu"
      data-studio-disclosure-menu
      data-active={arranging || undefined}
      data-arranging={arranging || undefined}
      onKeyDown={menu.onKeyDown}
      onToggle={menu.onToggle}
    >
      <summary
        ref={menu.triggerRef}
        className="studio-control studio-menu-trigger studio-icon-button studio-toolbar-action"
        aria-label="Workspace options"
      >
        <MoreIcon />
      </summary>
      <div className="studio-menu-popover studio-workspace-popover">
        <div className="studio-overflow-preview" hidden={!previewVisible}>
          <a
            className="studio-menu-item studio-overflow-popout"
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <PopoutIcon />
            <span>Open preview in new tab</span>
          </a>
          <div className="studio-menu-separator" />
        </div>
        <strong className="studio-menu-heading">Editor layout</strong>
        <ModeNavigation active={mode} onSelect={onModeSelect} />
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
};
