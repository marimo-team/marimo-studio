import { z } from "zod";

export const runtimeProgressSchema = z
  .strictObject({
    message: z
      .string()
      .min(1)
      .max(4_096)
      .refine((message) => message.length <= 4_096 && Array.from(message).length <= 2_048),
    completed: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER).optional(),
    total: z.int().positive().max(Number.MAX_SAFE_INTEGER).optional(),
  })
  .superRefine((progress, context) => {
    if (
      (progress.completed === undefined) !== (progress.total === undefined) ||
      (progress.completed !== undefined &&
        progress.total !== undefined &&
        progress.completed > progress.total)
    ) {
      context.addIssue({
        code: "custom",
        message: "Progress requires a completed count within its total",
      });
    }
  });

export type RuntimeProgress = z.infer<typeof runtimeProgressSchema>;
