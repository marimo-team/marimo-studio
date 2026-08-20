import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import { ProjectedOutputArea } from "@marimo-studio/marimo-frontend/projected-output";

export const ProjectedOutput = ({
  accessibleName,
  output,
  stale,
}: {
  accessibleName?: string;
  output: RenderedOutput;
  stale: boolean;
}) => <ProjectedOutputArea accessibleName={accessibleName} output={output} stale={stale} />;
