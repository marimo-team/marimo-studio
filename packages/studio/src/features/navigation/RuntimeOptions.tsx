import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";

import { AppWindowIcon, CircleHelpIcon, ServerIcon, type LucideIcon } from "lucide-react";

import { closeParentMenu } from "./menu.ts";
import { runtimeDescription } from "./model.ts";

const RUNTIME_ICONS: Readonly<Record<string, LucideIcon>> = {
  server: ServerIcon,
  wasm: AppWindowIcon,
};

export const RuntimeOptions = ({
  current,
  runtimes,
  onSelect,
}: {
  current: string;
  runtimes: readonly StudioRuntime[];
  onSelect: (runtime: string) => void;
}) => (
  <>
    {runtimes.map((runtime) => {
      const Icon = RUNTIME_ICONS[runtime.id] ?? CircleHelpIcon;
      return (
        <button
          key={runtime.id}
          type="button"
          className="studio-runtime-option"
          aria-pressed={runtime.id === current}
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
