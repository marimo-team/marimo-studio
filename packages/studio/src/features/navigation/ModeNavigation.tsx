import {
  Code2Icon,
  EyeIcon,
  NotebookTabsIcon,
  PanelsTopLeftIcon,
  type LucideIcon,
} from "lucide-react";

import type { StudioMode } from "../workspace/schema.ts";

import { closeParentMenu } from "./menu.ts";
import { OVERFLOW_MODES, PRIMARY_MODES, selectedMode } from "./model.ts";

const MODE_ICONS = {
  code: Code2Icon,
  notebook: NotebookTabsIcon,
  preview: EyeIcon,
  split: PanelsTopLeftIcon,
} as const satisfies Readonly<Record<Exclude<StudioMode, "workspace">, LucideIcon>>;

const NAVIGATION_VARIANTS = {
  overflow: {
    className: "studio-overflow-modes",
    grouped: false,
    itemClassName: "studio-menu-item",
    items: OVERFLOW_MODES,
  },
  primary: {
    className: "studio-modes studio-primary-modes",
    grouped: true,
    itemClassName: undefined,
    items: PRIMARY_MODES,
  },
} as const;

export const ModeNavigation = ({
  active,
  variant,
  onSelect,
}: {
  active: StudioMode;
  variant: keyof typeof NAVIGATION_VARIANTS;
  onSelect: (mode: Exclude<StudioMode, "workspace">) => void;
}) => {
  const config = NAVIGATION_VARIANTS[variant];
  const selected = selectedMode(active, config.grouped);
  const iconClassName = variant === "primary" ? "studio-mode-icon" : "studio-menu-item-icon";
  return (
    <nav className={config.className} aria-label="Studio mode">
      {config.items.map((item) => {
        const Icon = MODE_ICONS[item.mode];
        return (
          <button
            key={item.mode}
            type="button"
            className={config.itemClassName}
            data-studio-mode={item.mode}
            aria-pressed={selected === item.mode}
            onClick={(event) => {
              onSelect(item.mode);
              closeParentMenu(event.currentTarget);
            }}
          >
            <Icon className={iconClassName} strokeWidth={1.5} aria-hidden />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
};
