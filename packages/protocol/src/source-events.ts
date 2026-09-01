import { z } from "zod";

import { jsonCodec } from "./json.ts";
import { sourceDocumentPathSchema } from "./source-documents.ts";
import { viewNameSchema } from "./views.ts";

export const sourceFileChangeSchema = z.object({
  path: sourceDocumentPathSchema,
  revision: z.string().nullable(),
});

const sourceChangesSchema = z.object({
  files: z
    .array(sourceFileChangeSchema.optional().catch(undefined))
    .transform((files) => files.filter((file): file is SourceFileChange => file !== undefined)),
});
const sourceChangesCodec = jsonCodec(sourceChangesSchema);

export type SourceFileChange = z.infer<typeof sourceFileChangeSchema>;

const presentationBaselineSchema = z
  .object({
    schema: z.literal(1),
    view: viewNameSchema,
    revision: z.string().min(1).nullable(),
  })
  .strict();
const presentationBaselineCodec = jsonCodec(presentationBaselineSchema);

export type PresentationBaseline = z.infer<typeof presentationBaselineSchema>;

export const parsePresentationBaseline = (source: string): PresentationBaseline | undefined => {
  const result = presentationBaselineCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};

export const parseSourceChanges = (source: string): SourceFileChange[] => {
  const result = sourceChangesCodec.safeDecode(source);
  return result.success ? result.data.files : [];
};
