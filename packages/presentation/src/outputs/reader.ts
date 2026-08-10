import type { OutputReadRequest, OutputReadResponse } from "@marimo-studio/protocol/output-read";

export type OutputReader = (
  request: OutputReadRequest,
  signal?: AbortSignal,
) => Promise<OutputReadResponse>;
