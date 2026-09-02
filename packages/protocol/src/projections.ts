import { z } from "zod";

import { ownRecordSchema } from "./records.ts";
import { sourceDocumentPathSchema } from "./source-documents.ts";

export const MAX_ACTIVE_PROJECTION_INSTANCES = 512;
export const PROJECTION_UNPAIRED_SURROGATE_CODE = "projection-unpaired-surrogate";

export const projectionStringIsWellFormed = (value: string): boolean => value.isWellFormed();

export const projectionKindSchema = z.enum(["cell", "output", "value"]);
const projectionSiteIdSchema = z
  .string()
  .regex(
    /^[a-z0-9][a-z0-9._:-]{0,127}$/,
    "Projection site IDs must be lowercase artifact-local identifiers",
  );
const cellAliasPattern = /^[A-Za-z][A-Za-z0-9_-]*$/;
const nativeCellNamePattern = /^[_\p{ID_Start}][\p{ID_Continue}]*$/u;
const cellTargetIsValid = (value: string): boolean =>
  value !== "_" && (cellAliasPattern.test(value) || nativeCellNamePattern.test(value));
const projectionTargetNameSchema = z
  .string()
  .refine(projectionStringIsWellFormed, {
    message: PROJECTION_UNPAIRED_SURROGATE_CODE,
  })
  .refine((value) => value.length > 0 && value.trim() === value, {
    message: "Projection targets must be canonical non-empty strings",
  });

export const sourceLocationSchema = z
  .object({
    path: sourceDocumentPathSchema,
    line: z.int().positive(),
    column: z.int().positive(),
  })
  .strict();

export const mountDeclarationSchema = z
  .object({
    id: projectionSiteIdSchema,
    kind: projectionKindSchema,
    source: sourceLocationSchema,
    allowedTargets: z.array(projectionTargetNameSchema).nonempty().nullable(),
  })
  .strict()
  .superRefine((mount, context) => {
    if (
      mount.allowedTargets !== null &&
      new Set(mount.allowedTargets).size !== mount.allowedTargets.length
    ) {
      context.addIssue({
        code: "custom",
        path: ["allowedTargets"],
        message: "Mount declarations require unique allowed targets",
      });
    }
    if (
      mount.kind === "cell" &&
      mount.allowedTargets !== null &&
      mount.allowedTargets.some((target) => !cellTargetIsValid(target))
    ) {
      context.addIssue({
        code: "custom",
        path: ["allowedTargets"],
        message: "Cell targets must be canonical notebook cell names",
      });
    }
  });

const cellRefSchema = z.string().min(1);
export const projectionTargetSchema = z.discriminatedUnion("status", [
  z
    .object({
      status: z.literal("ready"),
      producer: cellRefSchema,
      dependencyClosure: z.array(cellRefSchema).nonempty(),
    })
    .strict(),
  z.object({ status: z.literal("ambiguous") }).strict(),
]);

export const projectionTargetsSchema = z
  .object({
    cells: ownRecordSchema(z.string().min(1), projectionTargetSchema),
    variables: ownRecordSchema(z.string().min(1), projectionTargetSchema),
  })
  .strict();

export const projectionPolicySchema = z
  .object({
    maxActiveInstances: z.int().positive(),
    maxUniqueCellTargets: z.int().positive(),
    maxUniqueOutputTargets: z.int().positive(),
    maxUniqueValueTargets: z.int().positive(),
    maxTargetBytes: z.int().positive(),
    maxPathSteps: z.int().positive(),
    maxInstanceIdBytes: z.int().positive(),
  })
  .strict();

export const runtimeBindingsSchema = z
  .object({
    cellRefs: ownRecordSchema(cellRefSchema, z.string().min(1)),
  })
  .strict();

export const projectionRequestSchema = z
  .object({
    siteId: z.string().min(1),
    instanceId: z.string().min(1).refine(projectionStringIsWellFormed, {
      message: PROJECTION_UNPAIRED_SURROGATE_CODE,
    }),
    target: z.string().min(1).refine(projectionStringIsWellFormed, {
      message: PROJECTION_UNPAIRED_SURROGATE_CODE,
    }),
  })
  .strict();

export const selectorPathStepSchema = z
  .object({
    kind: z.enum(["attribute", "item"]),
    value: z.union([z.string(), z.int().nonnegative().max(Number.MAX_SAFE_INTEGER)]),
  })
  .strict();

export const observedProjectionInstanceSchema = z
  .object({
    mountId: z.string().min(1).nullable(),
    instanceId: z.string().min(1),
    target: z.string(),
    runtimeCellId: z.string().min(1).nullable(),
    phase: z.enum(["connecting", "loading", "stale", "ready", "missing", "error"]),
    error: z
      .object({ code: z.string().min(1), message: z.string() })
      .strict()
      .nullable(),
  })
  .strict()
  .superRefine((instance, context) => {
    const resolved = instance.mountId !== null && instance.runtimeCellId !== null;
    if (instance.phase === "ready" && (!resolved || instance.error !== null)) {
      context.addIssue({
        code: "custom",
        message: "Ready projection instances require resolved source metadata and no error",
      });
    }
    if ((instance.phase === "error" || instance.phase === "missing") && instance.error === null) {
      context.addIssue({
        code: "custom",
        path: ["error"],
        message: "Failed projection instances require an error",
      });
    }
    if (instance.error !== null && instance.phase !== "error" && instance.phase !== "missing") {
      context.addIssue({
        code: "custom",
        path: ["error"],
        message: "Projection errors require an error or missing state",
      });
    }
  });

export type ObservedProjectionInstance = z.infer<typeof observedProjectionInstanceSchema>;
export type MountDeclaration = z.infer<typeof mountDeclarationSchema>;
export type ProjectionKind = z.infer<typeof projectionKindSchema>;
export type ProjectionPolicy = z.infer<typeof projectionPolicySchema>;
export type ProjectionRequest = z.infer<typeof projectionRequestSchema>;
export type ProjectionTarget = z.infer<typeof projectionTargetSchema>;
export type ProjectionTargets = z.infer<typeof projectionTargetsSchema>;
export type RuntimeBindings = z.infer<typeof runtimeBindingsSchema>;
export type SelectorPathStep = z.infer<typeof selectorPathStepSchema>;
export type SourceLocation = z.infer<typeof sourceLocationSchema>;

export const projectionInstanceIsReady = (instance: ObservedProjectionInstance): boolean =>
  instance.phase === "ready" &&
  instance.mountId !== null &&
  instance.runtimeCellId !== null &&
  instance.error === null;
