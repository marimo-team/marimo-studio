import { CellPresentation } from "@marimo-studio/marimo-frontend/cell-presentation";
import {
  projectedOutputFunctionOwner,
  type ProjectedOutputFunctionRequestScope,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";
import { useLayoutEffect, useState } from "react";

import type { RuntimeCell, SubmitStdin } from "../runtime-cell";
import type { CellProjection } from "./cell-projection";

export const CellOutput = ({
  cell,
  projectionRevision,
  projection,
  onSubmitStdin,
}: {
  cell: RuntimeCell;
  projectionRevision: string;
  projection: CellProjection;
  onSubmitStdin: SubmitStdin;
}) => {
  const activeOwner = projectedOutputFunctionOwner(projectionRevision, cell.lastRunStartTimestamp);
  const pendingOwner = projectedOutputFunctionOwner(projectionRevision, "pending");
  const [rendered, setRendered] = useState(() => ({
    cellId: cell.id,
    owner: projection.state === "ready" ? activeOwner : pendingOwner,
  }));
  const outputOwner = rendered.cellId === cell.id ? rendered.owner : pendingOwner;

  useLayoutEffect(() => {
    if (projection.state !== "ready") {
      return;
    }
    setRendered((current) =>
      current.cellId === cell.id && current.owner === activeOwner
        ? current
        : { cellId: cell.id, owner: activeOwner },
    );
  }, [activeOwner, cell.id, projection.state]);

  const functionRequestScope: ProjectedOutputFunctionRequestScope = {
    activeOwner,
    outputOwner,
  };
  return (
    <CellPresentation
      cell={cell}
      consoleOutputs={projection.consoleOutputs}
      functionRequestScope={functionRequestScope}
      loading={projection.loading}
      stale={projection.stale}
      onSubmitStdin={(text, outputIndex) => onSubmitStdin(cell, text, outputIndex)}
    />
  );
};
