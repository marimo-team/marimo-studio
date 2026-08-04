import { useMemo } from "react";

import type { CellIndex } from "../../cells/bindings";
import type { MarimoCellElement } from "../../cells/host";
import type { RuntimeCell, SubmitStdin } from "../runtime-cell";

import { useRuntimeConfig } from "../use-runtime-config";
import { projectCellHosts } from "./cell-host-projections";
import { CellPortal } from "./CellPortal";
import { DuplicateCellPortal } from "./DuplicateCellPortal";

export const RuntimeCellPortals = ({
  cells,
  hosts,
  runtimeReady,
  onSubmitStdin,
}: {
  cells: CellIndex<RuntimeCell>;
  hosts: readonly MarimoCellElement[];
  runtimeReady: boolean;
  onSubmitStdin: SubmitStdin;
}) => {
  const config = useRuntimeConfig();
  const projections = useMemo(() => projectCellHosts(config, cells, hosts), [cells, config, hosts]);

  return projections.map((projection) => {
    if (projection.kind === "duplicate") {
      return <DuplicateCellPortal key={projection.key} host={projection.host} />;
    }
    return (
      <CellPortal
        key={projection.key}
        host={projection.host}
        cell={projection.cell}
        bindingPresent={projection.bindingPresent}
        bindingKey={projection.bindingKey}
        developer={projection.developer}
        diagnostic={projection.diagnostic}
        runtimeReady={runtimeReady}
        onSubmitStdin={onSubmitStdin}
      />
    );
  });
};
