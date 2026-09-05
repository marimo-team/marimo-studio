import { memo } from "react";
import { createPortal } from "react-dom";

import type { MarimoCellElement } from "../../cells/host";
import type { ProjectionHostBinding } from "../../projections/resolution";
import type { RuntimeCell, SubmitStdin } from "../runtime-cell";
import type { CellDiagnostic } from "./cell-projection";

import { CellFallback } from "./CellFallback";
import { CellOutput } from "./CellOutput";
import { useCellHost } from "./use-cell-host";
import { useCellProjection } from "./use-cell-projection";

interface CellPortalProps {
  projectionKey?: string;
  projectionPresent: boolean;
  binding: ProjectionHostBinding;
  cell: RuntimeCell | undefined;
  developer: boolean;
  diagnostic?: CellDiagnostic;
  host: MarimoCellElement;
  onSubmitStdin: SubmitStdin;
  runtimeReady: boolean;
  showCellLogs: boolean;
}

export const CellPortal = memo(function CellPortal({
  projectionKey,
  projectionPresent,
  binding,
  cell,
  developer,
  diagnostic,
  host,
  onSubmitStdin,
  runtimeReady,
  showCellLogs,
}: CellPortalProps) {
  const projection = useCellProjection({
    alias: host.cellName,
    projectionKey,
    projectionPresent,
    cell,
    diagnostic,
    runtimeReady,
    showCellLogs,
  });
  useCellHost(host, binding, cell, projection);

  if (!cell) {
    if (!runtimeReady || projection.delivery === "waiting") {
      return null;
    }
    return createPortal(
      <CellFallback
        alias={host.cellName}
        developer={developer}
        diagnostic={projection.diagnostic}
        variant="missing"
      />,
      host,
    );
  }
  if (projection.loading && !projection.hasOutput) {
    return null;
  }
  if (projection.disabled && !projection.hasOutput) {
    return createPortal(
      <CellFallback alias={host.cellName} developer={developer} variant="disabled" />,
      host,
    );
  }

  return createPortal(
    <CellOutput
      cell={cell}
      projectionRevision={binding.projectionRevision}
      projection={projection}
      onSubmitStdin={onSubmitStdin}
    />,
    host,
  );
});
