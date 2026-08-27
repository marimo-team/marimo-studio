import type { PreviewStatus } from "../preview/status.ts";
import type { LayoutController } from "../workspace/controller.ts";
import type { StudioMode, Surface } from "../workspace/schema.ts";

export interface ModeItem {
  label: string;
  mode: Exclude<StudioMode, "workspace">;
}

export const PRIMARY_MODES: readonly ModeItem[] = [
  { label: "Notebook", mode: "notebook" },
  { label: "Develop", mode: "build" },
  { label: "Preview", mode: "preview" },
];

export const OVERFLOW_MODES: readonly ModeItem[] = [
  ...PRIMARY_MODES,
  { label: "Source", mode: "source" },
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

const GROUPED_MODES = {
  build: "build",
  notebook: "notebook",
  preview: "preview",
  source: "build",
  workspace: "build",
} as const satisfies Readonly<Record<StudioMode, ModeItem["mode"] | undefined>>;

const EXACT_MODES = {
  build: "build",
  notebook: "notebook",
  preview: "preview",
  source: "source",
  workspace: undefined,
} as const satisfies Readonly<Record<StudioMode, ModeItem["mode"] | undefined>>;

export const runtimeDescription = (runtime: string): string => {
  switch (runtime) {
    case "server":
      return "Uses the notebook kernel";
    case "wasm":
      return "Runs locally in your browser";
    default:
      return "Custom preview runtime";
  }
};

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
