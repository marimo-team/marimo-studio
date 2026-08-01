import type { flattenTopLevelNotebookCells } from "./upstream/cells";

export type RuntimeCell = ReturnType<
  typeof flattenTopLevelNotebookCells
>[number];
