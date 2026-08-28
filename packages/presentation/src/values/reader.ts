import type { ValueReadRequest } from "@marimo-studio/protocol/value-read";

import type { DecodedValueReadResponse } from "./codecs.ts";

export type ValueReader = (
  request: ValueReadRequest,
  signal?: AbortSignal,
) => Promise<DecodedValueReadResponse>;
