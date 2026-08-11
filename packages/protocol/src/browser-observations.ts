import { z } from "zod";

import { runtimeIdSchema } from "./runtime-config";

export const browserDiagnosticSchema = z
  .object({
    code: z.string().min(1),
    severity: z.enum(["warning", "error"]),
    message: z.string(),
    hint: z.string(),
    view: z.string().min(1),
    scope: z.string().min(1),
    projection: z.enum(["cell", "value", "output"]).optional(),
    target: z.string().optional(),
    source: z
      .object({
        path: z.string(),
        line: z.int().nonnegative(),
        column: z.int().nonnegative(),
      })
      .strict()
      .optional(),
  })
  .strict();

export const browserObservationSchema = z
  .object({
    schema: z.literal(1),
    view: z.string().min(1),
    runtime: runtimeIdSchema,
    revision: z.string().min(1),
    state: z.enum(["ready", "loading", "error"]),
    diagnostics: z.array(browserDiagnosticSchema).max(200),
    clientId: z.string().min(1),
    runtimeInstance: z.string().min(1),
    sessionId: z.string().min(1).nullable(),
    requestId: z.string().min(1),
    sequence: z.int().nonnegative(),
    query: z.string(),
  })
  .strict();

export type BrowserDiagnostic = z.infer<typeof browserDiagnosticSchema>;
export type BrowserObservation = z.infer<typeof browserObservationSchema>;
