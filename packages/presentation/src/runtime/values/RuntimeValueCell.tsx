import type { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";

import type { ValueReader } from "../../values/reader";
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
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  useRuntimeValue({ revision, selectors, cell, connectionState, runtimeReady, readValues });
  return null;
};
