import { z } from "zod";

import type { JsonValue } from "./runtime-config";

import { resolveUrl } from "./url.ts";
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

/** Parse a host record and resolve its URLs against the document that carried it. */
export const parseStudioHostBootstrap = (
  value: JsonValue,
  base: string | URL,
): StudioHostBootstrap => {
  const host = studioHostBootstrapSchema.parse(value);
  return {
    ...host,
    urls: {
      bootstrap: resolveUrl(host.urls.bootstrap, base),
      editor: resolveUrl(host.urls.editor, base),
      events: resolveUrl(host.urls.events, base),
      views: resolveUrl(host.urls.views, base),
    },
  };
};
