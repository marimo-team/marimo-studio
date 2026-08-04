import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import type { PreviewStatus } from "../../preview/status.ts";

import { MenuChevron } from "../icons.tsx";
import { runtimeStatusTitle } from "./model.ts";
import { RuntimeOptions } from "./RuntimeOptions.tsx";

export const RuntimeMenu = ({
  current,
  runtimes,
  status,
  visible,
  onSelect,
}: {
  current: StudioRuntime;
  runtimes: readonly StudioRuntime[];
  status: PreviewStatus;
  visible: boolean;
  onSelect: (runtime: string) => void;
}) => (
  <details className="studio-menu studio-runtime-menu" data-state={status.state} hidden={!visible}>
    <summary
      className="studio-runtime-trigger"
      aria-label={`${current.label} preview runtime`}
      title={runtimeStatusTitle(status)}
    >
      <span className="studio-runtime-dot" aria-hidden="true" />
      <span>{current.label}</span>
      <span className="studio-visually-hidden">{status.message}</span>
      <MenuChevron />
    </summary>
    <div className="studio-menu-popover studio-runtime-popover">
      <strong className="studio-menu-heading">Preview runtime</strong>
      <RuntimeOptions current={current.id} runtimes={runtimes} onSelect={onSelect} />
    </div>
  </details>
);
