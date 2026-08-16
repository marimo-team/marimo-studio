import type { PreviewStatus } from "../preview/status.ts";
import type { LayoutController } from "../workspace/controller.ts";
import type { StudioMode, Surface } from "../workspace/schema.ts";

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

const GROUPED_MODES = {
  code: "split",
  notebook: "notebook",
  preview: "preview",
  split: "split",
  workspace: "split",
} as const satisfies Readonly<Record<StudioMode, ModeItem["mode"] | undefined>>;

const EXACT_MODES = {
  code: "code",
  notebook: "notebook",
  preview: "preview",
  split: "split",
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
