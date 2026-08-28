import { z } from "zod";

import { MAX_ACTIVE_PROJECTION_INSTANCES, projectionRequestSchema } from "./projections.ts";
import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";

export const valueReadRequestSchema = z
  .object({
    revision: z.string().min(1),
    projections: z.array(projectionRequestSchema).max(MAX_ACTIVE_PROJECTION_INSTANCES),
    activeProjections: z.array(projectionRequestSchema).max(MAX_ACTIVE_PROJECTION_INSTANCES),
  })
  .refine(
    ({ projections, activeProjections }) => {
      const active = new Set(
        activeProjections.map(
          (projection) =>
            `${projection.siteId}\u0000${projection.instanceId}\u0000${projection.target}`,
        ),
      );
      return projections.every((projection) =>
        active.has(`${projection.siteId}\u0000${projection.instanceId}\u0000${projection.target}`),
      );
    },
    {
      message: "Every requested projection must also be active.",
      path: ["projections"],
    },
  );

export const valueReadErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  hint: z.string().optional(),
});

export const valueFingerprintSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/);

export const jsonValueDescriptorSchema = z
  .object({
    codec: z.literal("json-v1"),
    fingerprint: valueFingerprintSchema,
    value: jsonValueSchema,
  })
  .strict();

export const arrowValueDescriptorSchema = z
  .object({
    codec: z.literal("arrow-ipc-v1"),
    fingerprint: valueFingerprintSchema,
    dataUrl: z.string().min(1),
    byteLength: z.int().positive().max(Number.MAX_SAFE_INTEGER),
  })
  .strict();

export const valueDescriptorSchema = z.discriminatedUnion("codec", [
  jsonValueDescriptorSchema,
  arrowValueDescriptorSchema,
]);

export const valueReadResponseSchema = z.object({
  values: ownRecordSchema(z.string(), valueDescriptorSchema),
  errors: ownRecordSchema(z.string(), valueReadErrorSchema),
});

export type ArrowValueDescriptor = z.infer<typeof arrowValueDescriptorSchema>;
export type JsonValueDescriptor = z.infer<typeof jsonValueDescriptorSchema>;
export type ValueDescriptor = z.infer<typeof valueDescriptorSchema>;
export type ValueReadError = z.infer<typeof valueReadErrorSchema>;
export type ValueReadRequest = z.infer<typeof valueReadRequestSchema>;
export type ValueReadResponse = z.infer<typeof valueReadResponseSchema>;

export const parseValueReadResponse = (value: JsonValue): ValueReadResponse => {
  return valueReadResponseSchema.parse(value);
};
