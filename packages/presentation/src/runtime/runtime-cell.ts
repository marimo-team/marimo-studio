import type { flattenTopLevelNotebookCells } from "@marimo-studio/marimo-frontend/cells";

export type RuntimeCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

export type SubmitStdin = (cell: RuntimeCell, text: string, outputIndex: number) => void;
