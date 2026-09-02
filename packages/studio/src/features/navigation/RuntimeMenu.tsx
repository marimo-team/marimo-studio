import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import type { PreviewStatus } from "../preview/status.ts";

import { MenuChevron } from "../../shared/ui/icons.tsx";
import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";
import { RuntimeOptions } from "./RuntimeOptions.tsx";
import { RuntimeStatus } from "./RuntimeStatus.tsx";

export const RuntimeMenu = ({
  current,
  disabled,
  runtimes,
  status,
  visible,
  onSelect,
}: {
  current: StudioRuntime;
  disabled: boolean;
  runtimes: readonly StudioRuntime[];
  status: PreviewStatus;
  visible: boolean;
  onSelect: (runtime: string) => void;
}) => {
  const menu = useDisclosureMenu();
  return (
    <details
      ref={menu.detailsRef}
      className="studio-menu studio-runtime-menu"
      data-studio-disclosure-menu
      data-state={status.state}
      data-disabled={disabled || undefined}
      hidden={!visible}
      onKeyDown={menu.onKeyDown}
      onToggle={menu.onToggle}
    >
      <summary
        ref={menu.triggerRef}
        className="studio-control studio-menu-trigger studio-runtime-trigger"
        aria-label={`${current.label} preview runtime`}
        aria-disabled={disabled || undefined}
        onClick={(event) => {
          if (disabled) {
            event.preventDefault();
          }
        }}
      >
        <span className="studio-runtime-dot" aria-hidden="true" />
        <span>{current.label}</span>
        <span className="studio-visually-hidden">{status.message}</span>
        <MenuChevron />
      </summary>
      <div className="studio-menu-popover studio-runtime-popover">
        <strong className="studio-menu-heading">Run notebook with</strong>
        <RuntimeStatus status={status} />
        <RuntimeOptions
          current={current.id}
          disabled={disabled}
          runtimes={runtimes}
          onSelect={onSelect}
        />
      </div>
    </details>
  );
};
