import type { LayoutController } from "../workspace/controller.ts";
import type { StudioMode, Surface } from "../workspace/schema.ts";

export interface ModeItem {
  label: string;
  mode: Exclude<StudioMode, "workspace">;
}

export const PRIMARY_MODES: readonly ModeItem[] = [
  { label: "Notebook", mode: "notebook" },
  { label: "Develop", mode: "develop" },
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
  develop: "develop",
  notebook: "notebook",
  preview: "preview",
  source: "develop",
  workspace: "develop",
} as const satisfies Readonly<Record<StudioMode, ModeItem["mode"] | undefined>>;

const EXACT_MODES = {
  develop: "develop",
  notebook: "notebook",
  preview: "preview",
  source: "source",
  workspace: undefined,
} as const satisfies Readonly<Record<StudioMode, ModeItem["mode"] | undefined>>;

export const runtimeDescription = (runtime: string): string => {
  switch (runtime) {
    case "server":
      return "Use this editor's Python session for local files, databases, and secrets.";
    case "wasm":
      return "Run a separate notebook in the browser. The browser receives its source.";
    default:
      return "Custom preview runtime";
  }
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
