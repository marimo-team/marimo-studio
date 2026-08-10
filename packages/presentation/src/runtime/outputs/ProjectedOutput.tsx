import type { CellId, CellOutput } from "@marimo-studio/marimo-frontend/cells";
import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import { ProjectedOutputArea } from "@marimo-studio/marimo-frontend/projected-output";
import { useMemo } from "react";

export const ProjectedOutput = ({ output, stale }: { output: RenderedOutput; stale: boolean }) => {
  const message = useMemo<CellOutput>(
    () =>
      ({
        channel: "output",
        mimetype: output.mimetype,
        data: output.data,
        timestamp: output.timestamp,
      }) as CellOutput,
    [output],
  );
  return (
    <ProjectedOutputArea
      executionTime={output.timestamp}
      ownerCellId={output.ownerCellId as CellId}
      output={message}
      stale={stale}
    />
  );
};
