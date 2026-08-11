import { CellPresentation } from "@marimo-studio/marimo-frontend/cell-presentation";

import type { RuntimeCell, SubmitStdin } from "../runtime-cell";
import type { CellProjection } from "./cell-projection";

export const CellOutput = ({
  cell,
  projection,
  onSubmitStdin,
}: {
  cell: RuntimeCell;
  projection: CellProjection;
  onSubmitStdin: SubmitStdin;
}) => (
  <CellPresentation
    cell={cell}
    consoleOutputs={projection.consoleOutputs}
    loading={projection.loading}
    stale={projection.stale}
    onSubmitStdin={(text, outputIndex) => onSubmitStdin(cell, text, outputIndex)}
  />
);
