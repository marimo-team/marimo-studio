import { z } from "zod";

import type { JsonValue } from "./runtime-config";

import { ownerGenerationSchema, viewNameSchema } from "./views.ts";

const studioHostBaseSchema = z.object({
  schema: z.literal(1),
  notebook: z.object({
    name: z.string().trim().min(1),
  }),
  clientId: z.string().min(1),
  serverInstance: z.string().min(1),
  serverToken: z.string().min(1),
  urls: z.object({
    bootstrap: z.string().min(1),
    editor: z.string().min(1),
    events: z.string().min(1),
    views: z.string().min(1),
  }),
});

export const studioHostBootstrapSchema = z.discriminatedUnion("state", [
  studioHostBaseSchema.extend({ state: z.literal("unconfigured") }),
  studioHostBaseSchema.extend({
    state: z.literal("needs-view"),
    defaultView: viewNameSchema,
    generation: ownerGenerationSchema,
  }),
  studioHostBaseSchema.extend({ state: z.literal("ready") }),
]);

export type StudioHostBootstrap = z.infer<typeof studioHostBootstrapSchema>;

export const parseStudioHostBootstrap = (value: JsonValue): StudioHostBootstrap =>
  studioHostBootstrapSchema.parse(value);
