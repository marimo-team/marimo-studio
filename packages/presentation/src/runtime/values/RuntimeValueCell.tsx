import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { useRuntimeValue } from "./use-runtime-value";

export const RuntimeValueCell = ({
  revision,
  selectors,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  revision: string;
  selectors: string[];
  cell: RuntimeCell | undefined;
  connectionState: RuntimeConnectionState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  useRuntimeValue({ revision, selectors, cell, connectionState, runtimeReady, readValues });
  return null;
};
