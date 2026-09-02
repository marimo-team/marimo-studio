import { useMemo } from "react";

import type { RuntimeCell } from "../runtime-cell";

import { useDeliveryTimeout } from "../use-delivery-timeout";
import { type CellDiagnostic, projectCell } from "./cell-projection";

interface CellProjectionOptions {
  alias: string;
  projectionKey?: string;
  projectionPresent: boolean;
  cell: RuntimeCell | undefined;
  diagnostic?: CellDiagnostic;
  runtimeReady: boolean;
  showCellLogs: boolean;
}

export const useCellProjection = ({
  alias,
  projectionKey,
  projectionPresent,
  cell,
  diagnostic,
  runtimeReady,
  showCellLogs,
}: CellProjectionOptions) => {
  const waiting =
    runtimeReady && projectionPresent && cell === undefined && diagnostic === undefined;
  const deliveryTimedOut = useDeliveryTimeout(waiting, projectionKey);

  return useMemo(
    () =>
      projectCell({
        alias,
        projectionPresent,
        cell,
        diagnostic,
        deliveryTimedOut,
        runtimeReady,
        showCellLogs,
      }),
    [alias, cell, deliveryTimedOut, diagnostic, projectionPresent, runtimeReady, showCellLogs],
  );
};
