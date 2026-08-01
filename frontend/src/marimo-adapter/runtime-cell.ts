import type { flattenTopLevelNotebookCells } from "@marimo-team/frontend/unstable_internal/core/cells/cells";

export type RuntimeCell = ReturnType<
  typeof flattenTopLevelNotebookCells
>[number];
