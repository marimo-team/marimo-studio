import type { RenderedOutput } from "@marimo-studio/protocol/output-read";

import { ProjectedOutputArea } from "@marimo-studio/marimo-frontend/projected-output";

export const ProjectedOutput = ({ output, stale }: { output: RenderedOutput; stale: boolean }) => {
  return <ProjectedOutputArea output={output} stale={stale} />;
};
