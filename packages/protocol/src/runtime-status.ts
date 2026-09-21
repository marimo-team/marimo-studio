import { z } from "zod";

import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema } from "./runtime-config";
import { viewNameSchema } from "./views.ts";

export const browserDiagnosticSchema = z
  .object({
    code: z.string().min(1),
    severity: z.enum(["warning", "error"]),
    message: z.string(),
    hint: z.string(),
    view: viewNameSchema,
    scope: z.string().min(1),
    details: ownRecordSchema(z.string(), jsonValueSchema).optional(),
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

export type BrowserDiagnostic = z.infer<typeof browserDiagnosticSchema>;

export type RuntimeStatusPhase = "connecting" | "synchronizing" | "ready" | "degraded" | "failed";

export interface RuntimeStatusSnapshot {
  phase: RuntimeStatusPhase;
  diagnostics: BrowserDiagnostic[];
}

export interface RuntimeStatusTransition extends RuntimeStatusSnapshot {
  sequence: number;
  observedAt: number;
  revision: string | null;
  sessionId: string | null;
  diagnosticsTruncated: boolean;
}

export interface RuntimeStatusReport {
  runtime: string;
  view: string;
  revision: string | null;
  sessionId: string | null;
  current: RuntimeStatusSnapshot;
  transitions: RuntimeStatusTransition[];
}
