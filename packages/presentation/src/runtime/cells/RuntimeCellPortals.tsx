import { useMemo } from "react";

import type { MarimoCellElement } from "../../cells/host";
import type { CellIndex } from "../../cells/index";
import type { RuntimeCell, SubmitStdin } from "../runtime-cell";

import { useRuntimeProjectionConfig } from "../use-runtime-config";
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
  const config = useRuntimeProjectionConfig();
  const projections = useMemo(() => projectCellHosts(config, cells, hosts), [cells, config, hosts]);

  return projections.map((projection) => {
    if (projection.kind === "duplicate") {
      return (
        <DuplicateCellPortal
          key={projection.key}
          binding={projection.binding}
          host={projection.host}
        />
      );
    }
    return (
      <CellPortal
        key={projection.key}
        binding={projection.binding}
        host={projection.host}
        cell={projection.cell}
        projectionPresent={projection.projectionPresent}
        projectionKey={projection.projectionKey}
        developer={projection.developer}
        diagnostic={projection.diagnostic}
        runtimeReady={runtimeReady}
        showCellLogs={projection.showCellLogs}
        onSubmitStdin={onSubmitStdin}
      />
    );
  });
};
