import type { SessionId } from "@marimo-studio/marimo-frontend/runtime";

import type { OutputReader } from "../outputs/reader";
import type { ValueReader } from "../values/reader";

import { RuntimeCellPortals } from "./cells/RuntimeCellPortals";
import { RuntimeOutputs } from "./outputs/RuntimeOutputs";
import { useRuntimeCells } from "./session/use-runtime-cells";
import { RuntimeValues } from "./values/RuntimeValues";

export const RuntimeCellViews = ({
  initialized,
  readValues,
  readOutputs,
  sessionId,
}: {
  initialized: Promise<void>;
  readValues: ValueReader;
  readOutputs: OutputReader;
  sessionId: SessionId;
}) => {
  const runtime = useRuntimeCells({ initialized, sessionId });

  return (
    <>
      <RuntimeOutputs
        cells={runtime.cells}
        connectionState={runtime.connectionState}
        readOutputs={readOutputs}
        runtimeReady={runtime.runtimeReady}
      />
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
