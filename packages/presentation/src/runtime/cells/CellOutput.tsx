import { cellDomProps, ConsoleOutput, OutputArea } from "@marimo-studio/marimo-frontend/cells";

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
  <div className="marimo" data-marimo-cell-output="" {...cellDomProps(cell.id, cell.name)}>
    <ConsoleOutput
      cellId={cell.id}
      cellName="_"
      consoleOutputs={cell.consoleOutputs}
      stale={(cell.status === "queued" || cell.edited || cell.staleInputs) && !cell.interrupted}
      interrupted={cell.interrupted}
      debuggerActive={cell.debuggerActive}
      onSubmitDebugger={(text, outputIndex) => onSubmitStdin(cell, text, outputIndex)}
    />
    <OutputArea
      allowExpand={false}
      output={cell.output}
      cellId={cell.id}
      stale={projection.stale}
      loading={projection.loading}
    />
  </div>
);
