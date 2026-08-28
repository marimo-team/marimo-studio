import { z } from "zod";

import { runtimeIdSchema, type JsonValue } from "./runtime-config";

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
    defaultView: z.string().trim().min(1),
    selectedView: z.string().trim().min(1),
    views: z.array(z.string().trim().min(1)).min(1),
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

export const parseStudioBootstrap = (value: JsonValue): StudioBootstrap =>
  studioBootstrapSchema.parse(value);
