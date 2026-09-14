import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import { useId, useState } from "react";

import type { PreviewStatus } from "../preview/status.ts";

import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";
import { runtimeDescription } from "./model.ts";
import { RuntimeOptions } from "./RuntimeOptions.tsx";
import { RuntimeStatus } from "./RuntimeStatus.tsx";

const statusLabel = (status: PreviewStatus, runtime: string): string => {
  switch (status.state) {
    case "ready":
      return runtime === "zero-python" ? "Ready" : "Live";
    case "loading":
      return "Working";
    case "warning":
      return "Issues";
    case "error":
      return "Needs repair";
  }
};

export const RuntimeMenu = ({
  current,
  disabled,
  runtimes,
  status,
  visible,
  view,
  onSelect,
}: {
  current: StudioRuntime;
  disabled: boolean;
  runtimes: readonly StudioRuntime[];
  status: PreviewStatus;
  visible: boolean;
  view?: string;
  onSelect: (runtime: string) => void;
}) => {
  const menu = useDisclosureMenu();
  const tooltipId = useId();
  const [dismissed, setDismissed] = useState(false);
  return (
    <div
      className="studio-status-control"
      hidden={!visible}
      data-tooltip-dismissed={dismissed || undefined}
      onPointerEnter={() => setDismissed(false)}
      onFocus={() => setDismissed(false)}
    >
      <details
        ref={menu.detailsRef}
        className="studio-menu studio-runtime-menu"
        data-studio-disclosure-menu
        data-state={status.state}
        onKeyDown={(event) => {
          menu.onKeyDown(event);
          if (event.key === "Escape") setDismissed(true);
        }}
        onToggle={menu.onToggle}
      >
        <summary
          ref={menu.triggerRef}
          className="studio-control studio-menu-trigger studio-runtime-trigger"
          aria-label={`${current.label} preview runtime`}
          aria-describedby={tooltipId}
        >
          <span className="studio-status-label">{statusLabel(status, current.id)}</span>
        </summary>
        <div className="studio-menu-popover studio-runtime-popover">
          <strong className="studio-menu-heading">
            {view ? `${view} · ` : ""}
            {current.label}
          </strong>
          <RuntimeStatus status={status} />
          <p className="studio-runtime-context">{runtimeDescription(current.id)}</p>
          <div className="studio-menu-separator" />
          <strong className="studio-menu-heading">Run notebook with</strong>
          <RuntimeOptions
            current={current.id}
            disabled={disabled}
            runtimes={runtimes}
            onSelect={onSelect}
          />
        </div>
      </details>
      <div id={tooltipId} role="tooltip" className="studio-status-tooltip">
        <strong>
          {view ? `${view} · ` : ""}
          {current.label}
        </strong>
        <span>{status.message}</span>
        <span>{status.diagnostics[0]?.message ?? runtimeDescription(current.id)}</span>
        <small>Click for runtime details and diagnostics.</small>
      </div>
    </div>
  );
};
