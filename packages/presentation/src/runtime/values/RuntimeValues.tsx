import type { WebSocketState } from "@marimo-studio/marimo-frontend/runtime";

import { useMemo } from "react";

import type { CellIndex } from "../../cells/bindings";
import type { ValueReader } from "../../values/reader";
import type { RuntimeCell } from "../runtime-cell";

import { resolveCellBinding } from "../../cells/bindings";
import { useRuntimeConfig } from "../use-runtime-config";
import { RuntimeValueCell } from "./RuntimeValueCell";
import { groupValueBindings } from "./value-groups";

export const RuntimeValues = ({
  cells,
  connectionState,
  runtimeReady,
  readValues,
}: {
  cells: CellIndex<RuntimeCell>;
  connectionState: WebSocketState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  const config = useRuntimeConfig();
  const groups = useMemo(() => groupValueBindings(config.valueBindings), [config.valueBindings]);

  return groups.map(({ key, binding, selectors }) => (
    <RuntimeValueCell
      key={key}
      revision={config.revision}
      selectors={selectors}
      cell={resolveCellBinding(binding, cells)}
      connectionState={connectionState}
      runtimeReady={runtimeReady}
      readValues={readValues}
    />
  ));
};
