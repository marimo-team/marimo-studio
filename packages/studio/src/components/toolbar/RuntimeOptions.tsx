import type { StudioRuntime } from "@marimo-studio/protocol/studio-bootstrap";
import type { ComponentType } from "react";

import { BrowserIcon, ServerIcon, UnknownRuntimeIcon } from "../icons.tsx";
import { closeParentMenu } from "./menu.ts";
import { runtimeDescription } from "./model.ts";

const RUNTIME_ICONS: Readonly<Record<string, ComponentType>> = {
  server: ServerIcon,
  wasm: BrowserIcon,
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
      const Icon = RUNTIME_ICONS[runtime.id] ?? UnknownRuntimeIcon;
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
          <Icon />
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
