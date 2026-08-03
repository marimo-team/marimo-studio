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
