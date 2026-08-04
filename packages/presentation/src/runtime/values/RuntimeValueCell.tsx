import type { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";

import type { ValueReader } from "../../values/reader";
import type { RuntimeCell } from "../runtime-cell";

import { useRuntimeValue } from "./use-runtime-value";

export const RuntimeValueCell = ({
  selectors,
  cell,
  connectionState,
  runtimeReady,
  readValues,
}: {
  selectors: string[];
  cell: RuntimeCell | undefined;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  useRuntimeValue({ selectors, cell, connectionState, runtimeReady, readValues });
  return null;
};
