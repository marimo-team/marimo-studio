import { z } from "zod";

import {
  MAX_ACTIVE_PROJECTION_INSTANCES,
  observedProjectionInstanceSchema,
  projectionInstanceIsReady,
} from "./projections";
import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema, runtimeIdSchema } from "./runtime-config";
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

export const runtimeStatusPhaseSchema = z.enum([
  "connecting",
  "synchronizing",
  "ready",
  "degraded",
  "failed",
]);

export const runtimeStatusSnapshotSchema = z
  .object({
    phase: runtimeStatusPhaseSchema,
    diagnostics: z.array(browserDiagnosticSchema).max(200),
  })
  .strict()
  .superRefine((status, context) => {
    if (status.phase === "ready" && status.diagnostics.length > 0) {
      context.addIssue({
        code: "custom",
        message: "Ready runtime status cannot carry diagnostics",
        path: ["diagnostics"],
      });
    }
    if (
      (status.phase === "degraded" || status.phase === "failed") &&
      status.diagnostics.length === 0
    ) {
      context.addIssue({
        code: "custom",
        message: "Degraded and failed runtime status require diagnostics",
        path: ["diagnostics"],
      });
    }
  });

export const runtimeStatusTransitionSchema = z
  .object({
    sequence: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    observedAt: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    revision: z.string().min(1).nullable(),
    sessionId: z.string().min(1).nullable(),
    phase: runtimeStatusPhaseSchema,
    diagnostics: z.array(browserDiagnosticSchema).max(20),
    diagnosticsTruncated: z.boolean(),
  })
  .strict()
  .superRefine((status, context) => {
    if (status.phase === "ready" && status.diagnostics.length > 0) {
      context.addIssue({
        code: "custom",
        message: "Ready runtime transitions cannot carry diagnostics",
        path: ["diagnostics"],
      });
    }
    if (
      (status.phase === "degraded" || status.phase === "failed") &&
      status.diagnostics.length === 0
    ) {
      context.addIssue({
        code: "custom",
        message: "Degraded and failed runtime transitions require diagnostics",
        path: ["diagnostics"],
      });
    }
  });

export const runtimeStatusReportSchema = z
  .object({
    runtime: runtimeIdSchema,
    view: viewNameSchema,
    revision: z.string().min(1).nullable(),
    sessionId: z.string().min(1).nullable(),
    current: runtimeStatusSnapshotSchema,
    transitions: z.array(runtimeStatusTransitionSchema).min(1).max(32),
  })
  .strict()
  .superRefine((report, context) => {
    for (const [index, transition] of report.transitions.entries()) {
      const previous = report.transitions[index - 1];
      if (previous !== undefined && transition.sequence <= previous.sequence) {
        context.addIssue({
          code: "custom",
          message: "Runtime status transition sequences must increase",
          path: ["transitions", index, "sequence"],
        });
      }
    }
    const diagnostics = [
      ...report.current.diagnostics,
      ...report.transitions.flatMap((transition) => transition.diagnostics),
    ];
    if (diagnostics.some((diagnostic) => diagnostic.view !== report.view)) {
      context.addIssue({
        code: "custom",
        message: "Runtime status diagnostics must target the report view",
        path: ["view"],
      });
    }
    const latest = report.transitions.at(-1);
    const retained = report.current.diagnostics.slice(0, 20);
    const diagnosticsTruncated = retained.length < report.current.diagnostics.length;
    if (
      latest !== undefined &&
      (latest.phase !== report.current.phase ||
        latest.revision !== report.revision ||
        latest.sessionId !== report.sessionId ||
        JSON.stringify(latest.diagnostics) !== JSON.stringify(retained) ||
        latest.diagnosticsTruncated !== diagnosticsTruncated)
    ) {
      context.addIssue({
        code: "custom",
        message: "Current runtime status must match the latest transition",
        path: ["current"],
      });
    }
  });

export const browserObservationSchema = z
  .object({
    schema: z.literal(1),
    view: viewNameSchema,
    runtime: runtimeIdSchema,
    revision: z.string().min(1),
    state: z.enum(["ready", "loading", "error"]),
    diagnostics: z.array(browserDiagnosticSchema).max(200),
    clientId: z.string().min(1),
    runtimeInstance: z.string().min(1),
    sessionId: z.string().min(1).nullable(),
    requestId: z.string().min(1),
    sequence: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    query: z.string(),
    projectionInstances: z
      .array(observedProjectionInstanceSchema)
      .max(MAX_ACTIVE_PROJECTION_INSTANCES + 1),
    runtimeStatus: runtimeStatusReportSchema,
  })
  .strict()
  .superRefine((observation, context) => {
    const instanceIds = observation.projectionInstances.map((instance) => instance.instanceId);
    if (new Set(instanceIds).size !== instanceIds.length) {
      context.addIssue({
        code: "custom",
        message: "Projection instance identifiers must be unique",
        path: ["projectionInstances"],
      });
    }
    if (
      observation.state === "ready" &&
      !observation.projectionInstances.every(projectionInstanceIsReady)
    ) {
      context.addIssue({
        code: "custom",
        message: "Ready browser observations require every projection instance to be ready",
        path: ["projectionInstances"],
      });
    }
    const status = observation.runtimeStatus;
    const matches =
      status.runtime === observation.runtime &&
      status.view === observation.view &&
      status.revision === observation.revision &&
      status.sessionId === observation.sessionId;
    if (!matches) {
      context.addIssue({
        code: "custom",
        message: "Runtime status identity must match the browser observation",
        path: ["runtimeStatus"],
      });
    }
    if (JSON.stringify(status.current.diagnostics) !== JSON.stringify(observation.diagnostics)) {
      context.addIssue({
        code: "custom",
        message: "Runtime status diagnostics must match the browser observation",
        path: ["runtimeStatus", "current", "diagnostics"],
      });
    }
    let expectedPhase: RuntimeStatusPhase = "ready";
    if (observation.state === "loading") {
      expectedPhase = "synchronizing";
    } else if (observation.state === "error") {
      expectedPhase = "failed";
    } else if (observation.diagnostics.length > 0) {
      expectedPhase = "degraded";
    }
    const readyWithError =
      observation.state === "ready" &&
      observation.diagnostics.some((diagnostic) => diagnostic.severity === "error");
    if (status.current.phase !== expectedPhase || readyWithError) {
      context.addIssue({
        code: "custom",
        message: "Runtime status phase must match the browser observation state",
        path: ["runtimeStatus", "current", "phase"],
      });
    }
  });

export type BrowserDiagnostic = z.infer<typeof browserDiagnosticSchema>;
export type RuntimeStatusPhase = z.infer<typeof runtimeStatusPhaseSchema>;
export type RuntimeStatusSnapshot = z.infer<typeof runtimeStatusSnapshotSchema>;
export type RuntimeStatusTransition = z.infer<typeof runtimeStatusTransitionSchema>;
export type RuntimeStatusReport = z.infer<typeof runtimeStatusReportSchema>;
export type BrowserObservation = z.infer<typeof browserObservationSchema>;
