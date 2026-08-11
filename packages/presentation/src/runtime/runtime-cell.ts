import type { RuntimeCell as EmbeddedRuntimeCell } from "@marimo-studio/marimo-frontend/cell-presentation";

export type RuntimeCell = EmbeddedRuntimeCell;

export type SubmitStdin = (cell: RuntimeCell, text: string, outputIndex: number) => void;
