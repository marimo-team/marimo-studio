import { Code2Icon, EyeIcon, NotebookTabsIcon, PanelsTopLeftIcon } from "lucide-react";

import type { StudioMode } from "../workspace/schema.ts";

import { closeParentMenu } from "./menu.ts";

const commands = [
  { mode: "notebook", label: "Focus Notebook", Icon: NotebookTabsIcon },
  { mode: "develop", label: "Split Notebook and View", Icon: PanelsTopLeftIcon },
  { mode: "preview", label: "Focus View", Icon: EyeIcon },
  { mode: "source", label: "Focus Source", Icon: Code2Icon },
] as const;

export const ModeNavigation = ({
  active,
  onSelect,
}: {
  active: StudioMode;
  onSelect: (mode: Exclude<StudioMode, "workspace">) => void;
}) => (
  <div className="studio-layout-commands" role="group" aria-label="Editor layout">
    {commands.map(({ mode, label, Icon }) => (
      <button
        key={mode}
        type="button"
        className="studio-menu-item"
        aria-pressed={active === mode}
        onClick={(event) => {
          onSelect(mode);
          closeParentMenu(event.currentTarget);
        }}
      >
        <Icon className="studio-menu-item-icon" aria-hidden />
        <span>{label}</span>
      </button>
    ))}
  </div>
);
