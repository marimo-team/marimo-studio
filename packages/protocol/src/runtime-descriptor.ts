import { z } from "zod";

import type { JsonValue } from "./json.ts";

export const runtimeIdSchema = z.string().regex(/^[a-z][a-z0-9-]*$/);

export const runtimeDescriptorSchema = z
  .object({
    id: runtimeIdSchema,
    label: z.string().trim().min(1),
    description: z.string().trim().min(1),
    execution: z.enum(["kernel", "worker", "prepared"]),
    projections: z
      .object({
        cell: z.boolean(),
        output: z.boolean(),
        value: z.boolean(),
      })
      .strict(),
    controls: z.enum(["peer", "state", "none"]),
    query: z.enum(["reactive", "state", "none"]),
    preparation: z.enum(["primary", "after-primary", "on-select"]),
    session: z.enum(["shared", "isolated", "none"]),
  })
  .strict();

export type RuntimeDescriptor = z.infer<typeof runtimeDescriptorSchema>;

export const runtimeAvailabilitySchema = z
  .object({
    schema: z.literal(1),
    view: z.string().trim().min(1),
    runtimes: z.array(runtimeIdSchema).min(1),
    revision: z.string().min(1).nullable(),
    sources: z
      .object({
        "index.html": z.string().min(1),
        "app.css": z.string().min(1),
      })
      .strict(),
  })
  .strict()
  .refine((value) => new Set(value.runtimes).size === value.runtimes.length, {
    message: "Runtime availability requires unique runtime IDs",
    path: ["runtimes"],
  });

export type RuntimeAvailability = z.infer<typeof runtimeAvailabilitySchema>;

export const parseRuntimeAvailability = (value: JsonValue): RuntimeAvailability =>
  runtimeAvailabilitySchema.parse(value);
