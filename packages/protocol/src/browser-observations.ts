import { z } from "zod";

import { viewDiagnosticSchema } from "./preview-messages";
import { runtimeIdSchema } from "./runtime-config";

export const browserObservationSchema = z.object({
  schema: z.literal(1),
  view: z.string().min(1),
  runtime: runtimeIdSchema,
  revision: z.string().min(1),
  state: z.enum(["ready", "loading", "error"]),
  diagnostics: z.array(viewDiagnosticSchema),
});

export type BrowserObservation = z.infer<typeof browserObservationSchema>;
