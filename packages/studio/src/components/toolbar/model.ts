import type { LayoutController } from "../../layout/controller.ts";
import type { StudioMode, Surface } from "../../layout/schema.ts";
import type { PreviewStatus } from "../../preview/status.ts";

export interface ModeItem {
  label: string;
  mode: Exclude<StudioMode, "workspace">;
}

export const PRIMARY_MODES: readonly ModeItem[] = [
  { label: "Notebook", mode: "notebook" },
  { label: "Build", mode: "split" },
  { label: "Preview", mode: "preview" },
];

export const OVERFLOW_MODES: readonly ModeItem[] = [
  ...PRIMARY_MODES,
  { label: "HTML & CSS", mode: "code" },
];

export type WorkspaceAction = Parameters<LayoutController["applyAction"]>[0];

export const WORKSPACE_ACTION_GROUPS: readonly (readonly {
  action: WorkspaceAction;
  label: string;
}[])[] = [
  [
    { action: "workspace", label: "Open saved layout" },
    { action: "arrange", label: "Arrange panes" },
  ],
  [
    { action: "equalize", label: "Equalize split sizes" },
    { action: "reset", label: "Restore workspace" },
  ],
];

const GROUPED_MODES: Readonly<Record<StudioMode, ModeItem["mode"] | undefined>> = {
  code: "split",
  notebook: "notebook",
  preview: "preview",
  split: "split",
  workspace: "split",
};

const EXACT_MODES: Readonly<Record<StudioMode, ModeItem["mode"] | undefined>> = {
  code: "code",
  notebook: "notebook",
  preview: "preview",
  split: "split",
  workspace: undefined,
};

const RUNTIME_DESCRIPTIONS: Readonly<Record<string, string>> = {
  server: "Uses the notebook kernel",
  wasm: "Runs locally in your browser",
};

export const runtimeDescription = (runtime: string): string =>
  RUNTIME_DESCRIPTIONS[runtime] ?? "Custom preview runtime";

export const runtimeStatusTitle = (status: PreviewStatus): string => {
  if (!status.title) {
    return status.message;
  }
  return `${status.message}: ${status.title}`;
};

export const selectedMode = (active: StudioMode, grouped: boolean): ModeItem["mode"] | undefined =>
  (grouped ? GROUPED_MODES : EXACT_MODES)[active];

export const previewIsVisible = (
  compact: boolean,
  compactSurface: Surface,
  surfaces: readonly Surface[],
): boolean => {
  if (compact) {
    return compactSurface === "preview";
  }
  return surfaces.includes("preview");
};
