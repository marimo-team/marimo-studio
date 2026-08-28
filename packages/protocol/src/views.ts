import { z } from "zod";

import type { JsonValue } from "./runtime-config.ts";

import { starterIdSchema, starterSchema } from "./provider-catalog.ts";

const viewNameSchema = z.string().regex(/^[a-z][a-z0-9-]*$/, "Expected a canonical view name");

const viewSummarySchema = z
  .object({
    name: viewNameSchema,
  })
  .strict();

const viewListFields = {
  schema: z.literal(1),
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
  .object({ ...viewListFields, name: viewNameSchema })
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
export type DeletedView = z.infer<typeof deletedViewSchema>;

export const parseViewList = (payload: JsonValue): ViewList => {
  return viewListSchema.parse(payload);
};

export const parseCreatedView = (payload: JsonValue): CreatedView => {
  return createdViewSchema.parse(payload);
};

export const parseDeletedView = (payload: JsonValue): DeletedView => {
  return deletedViewSchema.parse(payload);
};
