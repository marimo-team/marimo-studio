import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import { ProjectedOutputArea } from "@marimo-studio/marimo-frontend/projected-output";
import { projectedOutputFunctionOwner } from "@marimo-studio/marimo-frontend/projected-output-function-gate";

export const ProjectedOutput = ({
  activeProjectionRevision,
  activeSourceVersion,
  output,
  outputProjectionRevision,
  outputSourceVersion,
  stale,
}: {
  activeProjectionRevision: string;
  activeSourceVersion: number | null;
  output: RenderedOutput;
  outputProjectionRevision: string;
  outputSourceVersion: number | null;
  stale: boolean;
}) => {
  return (
    <ProjectedOutputArea
      functionRequestScope={{
        activeOwner: projectedOutputFunctionOwner(activeProjectionRevision, activeSourceVersion),
        outputOwner: projectedOutputFunctionOwner(outputProjectionRevision, outputSourceVersion),
      }}
      output={output}
      stale={stale}
    />
  );
};
