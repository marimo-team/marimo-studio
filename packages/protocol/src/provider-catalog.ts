import { z } from "zod";

import { sourceDocumentPathSchema } from "./source-documents.ts";

export const providerKeySchema = z
  .string()
  .regex(
    /^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/,
    "Expected a distribution/entry-point provider key",
  );

export const starterIdSchema = z
  .string()
  .regex(
    /^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?:[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?$/,
    "Expected a provider-qualified starter identity",
  );

export const providerAvailabilitySchema = z
  .object({
    available: z.boolean(),
    version: z.string().nullable(),
    reason: z.string().nullable(),
    action: z.string().nullable(),
  })
  .strict();

export const starterSchema = z
  .object({
    schema: z.literal(1),
    id: starterIdSchema,
    provider: providerKeySchema,
    title: z.string().min(1),
    summary: z.string().min(1),
    documents: z.array(sourceDocumentPathSchema).min(1),
    availability: providerAvailabilitySchema,
  })
  .strict()
  .superRefine((starter, context) => {
    if (new Set(starter.documents).size !== starter.documents.length) {
      context.addIssue({
        code: "custom",
        path: ["documents"],
        message: "Starter documents must be unique",
      });
    }
  });

export type Starter = z.infer<typeof starterSchema>;
export type ProviderAvailability = z.infer<typeof providerAvailabilitySchema>;
