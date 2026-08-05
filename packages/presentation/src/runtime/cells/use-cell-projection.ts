import { useMemo } from "react";

import type { RuntimeCell } from "../runtime-cell";

import { useDeliveryTimeout } from "../use-delivery-timeout";
import { type CellDiagnostic, projectCell } from "./cell-projection";

interface CellProjectionOptions {
  alias: string;
  bindingKey?: string;
  bindingPresent: boolean;
  cell: RuntimeCell | undefined;
  diagnostic?: CellDiagnostic;
  runtimeReady: boolean;
  showCellLogs: boolean;
}

export const useCellProjection = ({
  alias,
  bindingKey,
  bindingPresent,
  cell,
  diagnostic,
  runtimeReady,
  showCellLogs,
}: CellProjectionOptions) => {
  const waiting = runtimeReady && bindingPresent && cell === undefined && diagnostic === undefined;
  const deliveryTimedOut = useDeliveryTimeout(waiting, bindingKey);

  return useMemo(
    () =>
      projectCell({
        alias,
        bindingPresent,
        cell,
        diagnostic,
        deliveryTimedOut,
        runtimeReady,
        showCellLogs,
      }),
    [alias, bindingPresent, cell, deliveryTimedOut, diagnostic, runtimeReady, showCellLogs],
  );
};
