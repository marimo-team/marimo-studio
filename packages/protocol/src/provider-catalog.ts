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

export const settingValueSchema = z.union([z.string(), z.boolean()]);

const settingFields = {
  key: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/),
  label: z.string().min(1),
  help: z.string().min(1),
};

/** One value a person can set before a starter creates a view's files. */
export const starterSettingSchema = z.discriminatedUnion("kind", [
  z
    .object({
      ...settingFields,
      kind: z.literal("boolean"),
      default: z.boolean(),
      choices: z.array(z.never()).length(0),
    })
    .strict(),
  z
    .object({
      ...settingFields,
      kind: z.literal("choice"),
      default: z.string(),
      choices: z
        .array(z.object({ value: z.string().min(1), label: z.string().min(1) }).strict())
        .min(1),
    })
    .strict()
    .refine((setting) => setting.choices.some((choice) => choice.value === setting.default), {
      message: "A choice setting's default must name one of its choices",
      path: ["default"],
    }),
  z
    .object({
      ...settingFields,
      kind: z.literal("text"),
      default: z.string(),
      choices: z.array(z.never()).length(0),
    })
    .strict(),
]);

export const starterSchema = z
  .object({
    schema: z.literal(1),
    id: starterIdSchema,
    provider: providerKeySchema,
    title: z.string().min(1),
    summary: z.string().min(1),
    documents: z.array(sourceDocumentPathSchema).min(1),
    availability: providerAvailabilitySchema,
    /** A short label for what the starter makes, such as "Web app" or "PDF". */
    format: z.string().min(1).max(40).nullable(),
    /** SVG markup of the technology's mark, painted in the theme's text color. */
    icon: z.string().min(1).max(16_384).nullable(),
    /** SHA-256 digest of the starter's preview image, or null without one. */
    preview: z
      .string()
      .regex(/^[0-9a-f]{64}$/)
      .nullable(),
    homepage: z.url({ protocol: /^https$/ }).nullable(),
    /** What the provider needs to build, such as "Quarto 1.9.38+". */
    requirement: z.string().min(1).nullable(),
    settings: z.array(starterSettingSchema),
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
export type StarterSetting = z.infer<typeof starterSettingSchema>;
export type SettingValue = z.infer<typeof settingValueSchema>;
export type ProviderAvailability = z.infer<typeof providerAvailabilitySchema>;
