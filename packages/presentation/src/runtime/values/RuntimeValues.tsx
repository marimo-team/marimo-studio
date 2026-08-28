import { useMemo, useSyncExternalStore } from "react";

import type { CellIndex } from "../../cells/index";
import type { ValueReader } from "../../values/reader";
import type { RuntimeConnectionState } from "../cell-state";
import type { RuntimeCell } from "../runtime-cell";

import { getValueHostProjections, subscribeValueHostProjections } from "../../values/hosts";
import { useRuntimeProjectionConfig } from "../use-runtime-config";
import { RuntimeValueCell } from "./RuntimeValueCell";
import { useValueLifecycle } from "./use-value-lifecycle";
import { groupValueProjections } from "./value-groups";

export const RuntimeValues = ({
  cells,
  connectionState,
  runtimeReady,
  readValues,
}: {
  cells: CellIndex<RuntimeCell>;
  connectionState: RuntimeConnectionState;
  runtimeReady: boolean;
  readValues: ValueReader;
}) => {
  const projectionConfig = useRuntimeProjectionConfig();
  const projections = useSyncExternalStore(
    subscribeValueHostProjections,
    getValueHostProjections,
    getValueHostProjections,
  );
  const groups = useMemo(
    () => groupValueProjections(projections, projectionConfig.projectionRevision),
    [projectionConfig.projectionRevision, projections],
  );
  const activeProjections = useMemo(() => groups.flatMap((group) => group.projections), [groups]);
  const ownedValueReader = useValueLifecycle({
    activeProjections,
    connectionState,
    projectionRevision: projectionConfig.projectionRevision,
    readValues,
    runtimeReady,
  });

  return groups.map(({ key, projections: requests, runtimeCellId, selectors }) => (
    <RuntimeValueCell
      key={key}
      projectionRevision={projectionConfig.projectionRevision}
      selectors={selectors}
      projections={requests}
      cell={runtimeCellId === undefined ? undefined : cells.byId.get(runtimeCellId)}
      connectionState={connectionState}
      runtimeReady={runtimeReady}
      readValues={ownedValueReader}
    />
  ));
};
