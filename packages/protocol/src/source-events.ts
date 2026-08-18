import { z } from "zod";

import { jsonCodec } from "./json.ts";

export const sourceNameSchema = z.enum(["index.html", "app.css"]);
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

const sourceBaselineSchema = z
  .object({
    schema: z.literal(1),
    view: z.string().min(1),
    revision: z.string().min(1).nullable(),
  })
  .strict();
const sourceBaselineCodec = jsonCodec(sourceBaselineSchema);

export type SourceBaseline = z.infer<typeof sourceBaselineSchema>;

export const parseSourceBaseline = (source: string): SourceBaseline | undefined => {
  const result = sourceBaselineCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};

export const parseSourceChanges = (source: string): SourceFileChange[] => {
  const result = sourceChangesCodec.safeDecode(source);
  return result.success ? result.data.files : [];
};
