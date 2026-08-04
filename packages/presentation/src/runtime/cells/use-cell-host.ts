import { useLayoutEffect } from "react";

import type { MarimoCellElement } from "../../cells/host";
import type { RuntimeCell } from "../runtime-cell";
import type { CellProjection } from "./cell-projection";

import { setCellHostState } from "../../cells/host";

const setDatasetValue = (dataset: DOMStringMap, name: string, value: string | undefined): void => {
  if (value === undefined || value === "") {
    delete dataset[name];
    return;
  }
  dataset[name] = value;
};

export const useCellHost = (
  host: MarimoCellElement,
  cell: RuntimeCell | undefined,
  projection: CellProjection,
): void => {
  useLayoutEffect(() => {
    setDatasetValue(host.dataset, "runtimeCellId", cell?.id);
    setDatasetValue(host.dataset, "outputMime", projection.outputMime);
    setDatasetValue(host.dataset, "outputMimes", projection.outputMimes);
    setDatasetValue(host.dataset, "marimoDiagnosticCode", projection.diagnostic?.code);
    setDatasetValue(host.dataset, "marimoDiagnosticMessage", projection.diagnostic?.message);
    setDatasetValue(host.dataset, "marimoDiagnosticHint", projection.diagnostic?.hint);
    setCellHostState(host, projection.state, {
      alias: host.cellName,
      runtimeId: cell?.id,
      outputMime: projection.outputMime,
      code: projection.diagnostic?.code,
      message: projection.diagnostic?.message,
      hint: projection.diagnostic?.hint,
    });
  }, [cell?.id, host, projection]);
};
