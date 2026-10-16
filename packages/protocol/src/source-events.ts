import { z } from "zod";

import type { JsonValue } from "./json.ts";

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

export type SourceFileChange = z.infer<typeof sourceFileChangeSchema>;

const presentationBaselineSchema = z
  .object({
    schema: z.literal(1),
    view: viewNameSchema,
    revision: z.string().min(1).nullable(),
  })
  .strict();

export type PresentationBaseline = z.infer<typeof presentationBaselineSchema>;

export const parsePresentationBaseline = (payload: JsonValue): PresentationBaseline | undefined => {
  const result = presentationBaselineSchema.safeParse(payload);
  return result.success ? result.data : undefined;
};

export const parseSourceChanges = (payload: JsonValue): SourceFileChange[] => {
  const result = sourceChangesSchema.safeParse(payload);
  return result.success ? result.data.files : [];
};
