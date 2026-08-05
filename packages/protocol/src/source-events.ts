import { z } from "zod";

import { jsonCodec } from "./json.ts";

export const sourceNameSchema = z.enum(["index.html", "theme.css", "app.css"]);
export const sourceFileChangeSchema = z.object({
  path: sourceNameSchema,
  revision: z.string().nullable(),
});

const sourceChangesSchema = z.object({
  files: z
    .array(sourceFileChangeSchema.optional().catch(undefined))
    .transform((files) => files.filter((file): file is SourceFileChange => file !== undefined)),
});
const sourceChangesCodec = jsonCodec(sourceChangesSchema);

export type SourceName = z.infer<typeof sourceNameSchema>;
export type SourceFileChange = z.infer<typeof sourceFileChangeSchema>;

export const parseSourceChanges = (source: string): SourceFileChange[] => {
  const result = sourceChangesCodec.safeDecode(source);
  return result.success ? result.data.files : [];
};
