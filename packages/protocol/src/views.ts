import { z } from "zod";

import type { JsonValue } from "./runtime-config.ts";

import { starterIdSchema, starterSchema } from "./provider-catalog.ts";

export const VIEW_NAME_MAX_BYTES = 240;

const utf8 = new TextEncoder();
const viewNamePattern = /^[a-z][a-z0-9-]*$/;
const windowsDeviceName = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i;
const reservedViewNames = new Set([
  "_marimo-studio",
  "api",
  "assets",
  "auth",
  "favicon.ico",
  "health",
  "healthz",
  "lsp",
  "mcp",
  "og",
  "public",
  "sse",
  "studio",
  "terminal",
  "ws",
]);

export const viewNameError = (name: string): string | undefined => {
  if (!viewNamePattern.test(name)) {
    return "View names must start with a lowercase letter and contain lowercase letters, digits, or hyphens.";
  }
  if (reservedViewNames.has(name)) {
    return `View name '${name}' is reserved.`;
  }
  if (windowsDeviceName.test(name)) {
    return "View name contains a reserved Windows device name";
  }
  if (utf8.encode(name).byteLength > VIEW_NAME_MAX_BYTES) {
    return `View name exceeds the ${VIEW_NAME_MAX_BYTES}-byte limit`;
  }
  return undefined;
};

export const viewNameSchema = z.string().superRefine((name, context) => {
  const message = viewNameError(name);
  if (message) {
    context.addIssue({ code: "custom", message });
  }
});

export const ownerGenerationSchema = z.string().regex(/^[a-f0-9]{64}$/);

const viewSummarySchema = z
  .object({
    generation: ownerGenerationSchema,
    name: viewNameSchema,
  })
  .strict();

export const deleteViewRequestSchema = z
  .object({
    catalog_generation: ownerGenerationSchema,
    name: viewNameSchema,
    view_generation: ownerGenerationSchema,
  })
  .strict();

export const createViewRequestSchema = z
  .object({
    catalog_generation: ownerGenerationSchema,
    name: viewNameSchema,
    starter: starterIdSchema,
  })
  .strict();

const viewListFields = {
  schema: z.literal(1),
  generation: ownerGenerationSchema,
  default_view: viewNameSchema,
  default_starter: starterIdSchema,
  views: z.array(viewSummarySchema),
  starters: z.array(starterSchema),
};

const includesDefaultView = (value: { default_view: string; views: { name: string }[] }) =>
  value.views.length === 0 || value.views.some((view) => view.name === value.default_view);

const includesDefaultStarter = (value: { default_starter: string; starters: { id: string }[] }) =>
  value.starters.some((starter) => starter.id === value.default_starter);

const uniqueInventory = (
  value: { views: { name: string }[]; starters: { id: string }[] },
  context: z.RefinementCtx,
) => {
  const views = value.views.map((view) => view.name);
  if (new Set(views).size !== views.length) {
    context.addIssue({ code: "custom", path: ["views"], message: "View names must be unique" });
  }
  const starters = value.starters.map((starter) => starter.id);
  if (new Set(starters).size !== starters.length) {
    context.addIssue({
      code: "custom",
      path: ["starters"],
      message: "Starter identities must be unique",
    });
  }
};

export const viewListSchema = z
  .object(viewListFields)
  .strict()
  .refine(includesDefaultView, {
    message: "The default view must be present in the view list.",
    path: ["default_view"],
  })
  .refine(includesDefaultStarter, {
    message: "The default starter must be present in the starter catalog.",
    path: ["default_starter"],
  })
  .superRefine(uniqueInventory);
export const createdViewSchema = z
  .object({
    schema: z.literal(1),
    name: viewNameSchema,
  })
  .strict();
export const deletedViewSchema = z
  .object({
    ...viewListFields,
    cleanup: z.string().min(1).nullable().optional(),
    name: viewNameSchema,
  })
  .strict()
  .refine(includesDefaultView, {
    message: "The default view must be present in the view list.",
    path: ["default_view"],
  })
  .refine(includesDefaultStarter, {
    message: "The default starter must be present in the starter catalog.",
    path: ["default_starter"],
  })
  .superRefine(uniqueInventory)
  .superRefine((inventory, context) => {
    if (inventory.views.length === 0) {
      context.addIssue({
        code: "custom",
        path: ["views"],
        message: "A deleted view response must retain an available view",
      });
    }
    if (inventory.views.some((view) => view.name === inventory.name)) {
      context.addIssue({
        code: "custom",
        path: ["name"],
        message: "The deleted view must be absent from the remaining inventory",
      });
    }
  });

export type ViewList = z.infer<typeof viewListSchema>;
export type CreatedView = z.infer<typeof createdViewSchema>;
export type CreateViewRequest = z.infer<typeof createViewRequestSchema>;
export type DeletedView = z.infer<typeof deletedViewSchema>;
export type DeleteViewRequest = z.infer<typeof deleteViewRequestSchema>;

export const parseViewList = (payload: JsonValue): ViewList => {
  return viewListSchema.parse(payload);
};

export const parseCreatedView = (payload: JsonValue): CreatedView => {
  return createdViewSchema.parse(payload);
};

export const parseDeletedView = (payload: JsonValue): DeletedView => {
  return deletedViewSchema.parse(payload);
};
