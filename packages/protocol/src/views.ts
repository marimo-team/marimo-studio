import { z } from "zod";

const viewListFields = {
  schema: z.literal(1),
  default_view: z.string(),
  views: z.array(z.string()),
};

const includesDefaultView = (value: { default_view: string; views: string[] }) =>
  value.views.includes(value.default_view);

export const viewListSchema = z.object(viewListFields).refine(includesDefaultView, {
  message: "The default view must be present in the view list.",
  path: ["default_view"],
});
export const createdViewSchema = z.object({
  schema: z.literal(1),
  name: z.string(),
});
export const deletedViewSchema = z
  .object({ ...viewListFields, name: z.string() })
  .refine(includesDefaultView, {
    message: "The default view must be present in the view list.",
    path: ["default_view"],
  });

export type ViewList = z.infer<typeof viewListSchema>;
export type CreatedView = z.infer<typeof createdViewSchema>;
export type DeletedView = z.infer<typeof deletedViewSchema>;

export const parseViewList = (payload: unknown): ViewList => {
  return viewListSchema.parse(payload);
};

export const parseCreatedView = (payload: unknown): CreatedView => {
  return createdViewSchema.parse(payload);
};

export const parseDeletedView = (payload: unknown): DeletedView => {
  return deletedViewSchema.parse(payload);
};
