import type { MarimoCellOutputSnapshot } from "./projected-output.tsx";
import type { CellId } from "./upstream/cells.ts";

import { ProjectedCellPresentation } from "./cell-presentation.tsx";
import { toMarimoCellOutput, useProjectedOutputOwner } from "./projected-output.tsx";

export interface PreparedCellPresentationSnapshot {
  readonly accessibleName: string;
  readonly cellId: string;
  readonly cellName: string;
  readonly consoleOutputs: readonly MarimoCellOutputSnapshot[];
  readonly output: MarimoCellOutputSnapshot | null;
}

const consoleOutput = (output: MarimoCellOutputSnapshot) => {
  if (output.channel === "stdin" || output.channel === "pdb") {
    throw new Error(`Prepared cell snapshots cannot render ${output.channel} interaction`);
  }
  return toMarimoCellOutput(output);
};

const rejectStdin = (): never => {
  throw new Error("Prepared cell snapshots cannot submit stdin");
};

export const PreparedCellPresentation = ({
  snapshot,
}: {
  snapshot: PreparedCellPresentationSnapshot;
}) => {
  if (snapshot.cellId.length === 0) {
    throw new Error("A prepared cell snapshot requires a cell identifier");
  }
  // SAFETY: Marimo brands every nonempty runtime cell identifier after wire validation.
  const cellId = snapshot.cellId as CellId;
  const output = snapshot.output === null ? null : toMarimoCellOutput(snapshot.output);
  const timestamp = output?.timestamp ?? snapshot.consoleOutputs.at(-1)?.timestamp ?? 0;
  const registered = useProjectedOutputOwner(cellId, timestamp);
  if (!registered) {
    return null;
  }
  const consoleOutputs = snapshot.consoleOutputs.map(consoleOutput);

  return (
    <ProjectedCellPresentation
      accessibleName={snapshot.accessibleName}
      cellId={cellId}
      cellName={snapshot.cellName}
      consoleOutputs={consoleOutputs}
      interrupted={false}
      loading={false}
      output={output}
      stale={false}
      onSubmitStdin={rejectStdin}
    />
  );
};
