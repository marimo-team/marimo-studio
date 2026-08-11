import { Fragment, type ReactNode } from "react";

import type { OutputReader } from "../outputs/reader";
import type { RuntimeCellSource } from "../runtime/session/use-runtime-cells";
import type { ValueReader } from "../values/reader";

import { RuntimeCellPortals } from "../runtime/cells/RuntimeCellPortals";
import { RuntimeOutputs } from "../runtime/outputs/RuntimeOutputs";
import { useRuntimeCells } from "../runtime/session/use-runtime-cells";
import { RuntimeValues } from "../runtime/values/RuntimeValues";

interface RuntimeProjectionProps {
  readValues: ValueReader;
  readOutputs: OutputReader;
  runtime: RuntimeCellSource;
}

export const RuntimeProjections = ({
  readValues,
  readOutputs,
  runtime: source,
}: RuntimeProjectionProps) => {
  const runtime = useRuntimeCells(source);
  const projections: readonly { kind: string; view: ReactNode }[] = [
    {
      kind: "output",
      view: (
        <RuntimeOutputs
          cells={runtime.cells}
          connectionState={runtime.connectionState}
          readOutputs={readOutputs}
          runtimeReady={runtime.runtimeReady}
        />
      ),
    },
    {
      kind: "value",
      view: (
        <RuntimeValues
          cells={runtime.cells}
          connectionState={runtime.connectionState}
          runtimeReady={runtime.runtimeReady}
          readValues={readValues}
        />
      ),
    },
    {
      kind: "cell",
      view: (
        <RuntimeCellPortals
          cells={runtime.cells}
          hosts={runtime.hosts}
          runtimeReady={runtime.runtimeReady}
          onSubmitStdin={runtime.submitStdin}
        />
      ),
    },
  ];

  return projections.map((projection) => (
    <Fragment key={projection.kind}>{projection.view}</Fragment>
  ));
};
