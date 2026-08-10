import { z } from "zod";

import { jsonCodec } from "./json.ts";

export const shellChangeKindSchema = z.enum(["css", "html", "runtime", "views"]);
const shellChangeSchema = z.object({ kind: shellChangeKindSchema });
const shellChangeCodec = jsonCodec(shellChangeSchema);

export type ShellChangeKind = z.infer<typeof shellChangeKindSchema>;

export const parseShellChange = (source: string): ShellChangeKind | undefined => {
  const result = shellChangeCodec.safeDecode(source);
  return result.success ? result.data.kind : undefined;
};

const activeViewSchema = z.object({
  schema: z.literal(1),
  view: z.string().min(1),
});
const activeViewCodec = jsonCodec(activeViewSchema);

export type ActiveViewRequest = z.infer<typeof activeViewSchema>;

export const parseActiveViewRequest = (source: string): ActiveViewRequest | undefined => {
  const result = activeViewCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};
