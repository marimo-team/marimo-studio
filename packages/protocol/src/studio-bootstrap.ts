import { z } from "zod";

import { runtimeIdSchema, type JsonValue } from "./runtime-config";
import { resolveUrl } from "./url.ts";
import { viewNameSchema } from "./views.ts";

export const studioRuntimeSchema = z.object({
  id: runtimeIdSchema,
  label: z.string().trim().min(1),
});

export const studioBootstrapSchema = z
  .object({
    schema: z.literal(1),
    notebook: z.object({
      name: z.string().trim().min(1),
    }),
    defaultView: viewNameSchema,
    selectedView: viewNameSchema,
    views: z.array(viewNameSchema).min(1),
    runtimes: z.array(studioRuntimeSchema).min(1),
    defaultRuntime: z.string().trim().min(1),
    urls: z.object({
      editor: z.string().min(1),
      agent: z.string().min(1),
      events: z.string().min(1),
      query: z.string().min(1),
      studioPrefix: z.string().min(1),
      viewPrefix: z.string().min(1),
      viewSupportPrefix: z.string().min(1),
      views: z.string().min(1),
    }),
    workspaceId: z.string().min(1),
    clientId: z.string().min(1),
    serverInstance: z.string().min(1),
    serverToken: z.string().min(1),
  })
  .superRefine((value, context) => {
    if (new Set(value.views).size !== value.views.length) {
      context.addIssue({
        code: "custom",
        path: ["views"],
        message: "Views must have unique names",
      });
    }
    const runtimeIds = value.runtimes.map((runtime) => runtime.id);
    if (new Set(runtimeIds).size !== runtimeIds.length) {
      context.addIssue({
        code: "custom",
        path: ["runtimes"],
        message: "Runtimes must have unique identifiers",
      });
    }
    if (!value.views.includes(value.selectedView)) {
      context.addIssue({
        code: "custom",
        path: ["selectedView"],
        message: "Selected view is not present in views",
      });
    }
    if (!value.views.includes(value.defaultView)) {
      context.addIssue({
        code: "custom",
        path: ["defaultView"],
        message: "Default view is not present in views",
      });
    }
    if (!value.runtimes.some((runtime) => runtime.id === value.defaultRuntime)) {
      context.addIssue({
        code: "custom",
        path: ["defaultRuntime"],
        message: "Default runtime is not present in runtimes",
      });
    }
  });

export type StudioRuntime = z.infer<typeof studioRuntimeSchema>;
export type StudioBootstrap = z.infer<typeof studioBootstrapSchema>;

/**
 * Parse a workspace bootstrap and resolve its URLs against the response or
 * document that carried it.
 */
export const parseStudioBootstrap = (value: JsonValue, base: string | URL): StudioBootstrap => {
  const bootstrap = studioBootstrapSchema.parse(value);
  const { urls } = bootstrap;
  return {
    ...bootstrap,
    urls: {
      editor: resolveUrl(urls.editor, base),
      agent: resolveUrl(urls.agent, base),
      events: resolveUrl(urls.events, base),
      query: resolveUrl(urls.query, base),
      studioPrefix: resolveUrl(urls.studioPrefix, base),
      viewPrefix: resolveUrl(urls.viewPrefix, base),
      viewSupportPrefix: resolveUrl(urls.viewSupportPrefix, base),
      views: resolveUrl(urls.views, base),
    },
  };
};
