import type { RuntimeProjectionRequest as ProjectionRequest } from "../../projections/resolution";
import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { useRuntimeValue } from "./use-runtime-value";

export const RuntimeValueCell = ({
  projectionRevision,
  selectors,
  projections,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  projectionRevision: string;
  selectors: string[];
  projections: ProjectionRequest[];
  cell: RuntimeCell | undefined;
  connectionState: RuntimeConnectionState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  useRuntimeValue({
    projectionRevision,
    selectors,
    projections,
    cell,
    connectionState,
    runtimeReady,
    readValues,
  });
  return null;
};
