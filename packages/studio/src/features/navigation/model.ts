import type { LayoutController } from "../workspace/controller.ts";
import type { Surface } from "../workspace/schema.ts";

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

export const runtimeDescription = (runtime: string): string => {
  switch (runtime) {
    case "server":
      return "Use this editor's Python session for local files, databases, and secrets.";
    case "wasm":
      return "Run a separate notebook in the browser. The browser receives its source.";
    case "zero-python":
      return "Precomputed states, zero Python";
    default:
      return "Custom preview runtime";
  }
};

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
