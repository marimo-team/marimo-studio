import type { ValueReadResponse } from "@marimo-studio/protocol/value-read";

export type ValueReader = (selectors: string[], signal?: AbortSignal) => Promise<ValueReadResponse>;
