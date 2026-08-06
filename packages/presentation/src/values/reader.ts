import type { ValueReadRequest, ValueReadResponse } from "@marimo-studio/protocol/value-read";

export type ValueReader = (
  request: ValueReadRequest,
  signal?: AbortSignal,
) => Promise<ValueReadResponse>;
