import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import {
  AppWindowIcon,
  CircleHelpIcon,
  LayersIcon,
  ServerIcon,
  type LucideIcon,
} from "lucide-react";

import { closeParentMenu } from "./menu.ts";
import { runtimeDescription } from "./model.ts";

const runtimeIcon = (runtime: string): LucideIcon => {
  switch (runtime) {
    case "server":
      return ServerIcon;
    case "wasm":
      return AppWindowIcon;
    case "zero-python":
      return LayersIcon;
    default:
      return CircleHelpIcon;
  }
};

export const RuntimeOptions = ({
  current,
  disabled,
  runtimes,
  onSelect,
}: {
  current: string;
  disabled: boolean;
  runtimes: readonly StudioRuntime[];
  onSelect: (runtime: string) => void;
}) => (
  <>
    {runtimes.map((runtime) => {
      const Icon = runtimeIcon(runtime.id);
      return (
        <button
          key={runtime.id}
          type="button"
          className="studio-runtime-option"
          aria-pressed={runtime.id === current}
          disabled={disabled}
          onClick={(event) => {
            onSelect(runtime.id);
            closeParentMenu(event.currentTarget);
          }}
        >
          <Icon className="studio-runtime-icon" aria-hidden />
          <span className="studio-runtime-copy">
            <strong>{runtime.label}</strong>
            <span>{runtimeDescription(runtime.id)}</span>
          </span>
          <span className="studio-runtime-check" aria-hidden="true">
            ✓
          </span>
        </button>
      );
    })}
  </>
);
