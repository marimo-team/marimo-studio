import type { OutputReadResponse } from "@marimo-studio/protocol/output-read";

import { reconcileProjectedOutput } from "@marimo-studio/marimo-frontend/projected-output";

export const reconcileOutputReadResponse = (response: OutputReadResponse): OutputReadResponse => {
  for (const output of Object.values(response.outputs)) {
    reconcileProjectedOutput(output);
  }
  return response;
};
