import type { JsonValue, UnparsedJsonValue } from "@marimo-team/portable-json";

import { jsonValueSchema } from "@marimo-team/portable-json/zod";

export type EmbeddedJsonValue = JsonValue;

export const parseEmbeddedJsonValue = (value: UnparsedJsonValue): EmbeddedJsonValue =>
  jsonValueSchema.parse(value);
