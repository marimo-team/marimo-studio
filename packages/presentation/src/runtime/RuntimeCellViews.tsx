import type { SessionId } from "@marimo-studio/marimo-frontend/runtime";

import type { ValueReader } from "../values/reader";

import { RuntimeCellPortals } from "./cells/RuntimeCellPortals";
import { useRuntimeCells } from "./session/use-runtime-cells";
import { RuntimeValues } from "./values/RuntimeValues";

export const RuntimeCellViews = ({
  initialized,
  readValues,
  sessionId,
}: {
  initialized: Promise<void>;
  readValues: ValueReader;
  sessionId: SessionId;
}) => {
  const runtime = useRuntimeCells({ initialized, sessionId });

  return (
    <>
      <RuntimeValues
        cells={runtime.cells}
        connectionState={runtime.connectionState}
        runtimeReady={runtime.runtimeReady}
        readValues={readValues}
      />
      <RuntimeCellPortals
        cells={runtime.cells}
        hosts={runtime.hosts}
        runtimeReady={runtime.runtimeReady}
        onSubmitStdin={runtime.submitStdin}
      />
    </>
  );
};
