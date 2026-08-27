import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import type { PreviewStatus } from "../preview/status.ts";

import { MenuChevron } from "../../shared/ui/icons.tsx";
import { runtimeStatusTitle } from "./model.ts";
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
}) => (
  <details
    className="studio-menu studio-runtime-menu"
    data-state={status.state}
    data-disabled={disabled || undefined}
    hidden={!visible}
  >
    <summary
      className="studio-control studio-menu-trigger studio-runtime-trigger"
      aria-label={`${current.label} preview runtime`}
      aria-disabled={disabled || undefined}
      title={runtimeStatusTitle(status)}
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
      <strong className="studio-menu-heading">Preview runtime</strong>
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
