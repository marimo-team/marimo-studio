import { z } from "zod";

import type { JsonValue } from "./runtime-config.ts";

import { projectionRequestSchema } from "./projections.ts";
import { ownRecordSchema } from "./records.ts";
import { valueReadErrorSchema } from "./value-read.ts";

export const MAX_OUTPUT_SELECTORS = 100;

export const outputReadRequestSchema = z
  .object({
    revision: z.string().min(1),
    projections: z.array(projectionRequestSchema).max(MAX_OUTPUT_SELECTORS),
    activeProjections: z.array(projectionRequestSchema).max(MAX_OUTPUT_SELECTORS),
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

export const renderedOutputSchema = z
  .object({
    ownerCellId: z.string().min(1),
    mimetype: z.string().min(1),
    data: z.string(),
    timestamp: z.number(),
    resetUiObjectIds: z.array(z.string().min(1)),
  })
  .refine(
    ({ ownerCellId, resetUiObjectIds }) =>
      resetUiObjectIds.every((objectId) => objectId.startsWith(`${ownerCellId}-`)),
    {
      message: "A projected output may reset only UI objects owned by its projection.",
      path: ["resetUiObjectIds"],
    },
  );

export const outputReadResponseSchema = z.object({
  outputs: ownRecordSchema(z.string(), renderedOutputSchema),
  errors: ownRecordSchema(z.string(), valueReadErrorSchema),
  overlays: ownRecordSchema(z.string(), renderedOutputSchema).optional(),
});

export type OutputReadRequest = z.infer<typeof outputReadRequestSchema>;
export type OutputReadResponse = z.infer<typeof outputReadResponseSchema>;
export type RenderedOutput = z.infer<typeof renderedOutputSchema>;

export const parseOutputReadResponse = (value: JsonValue): OutputReadResponse => {
  return outputReadResponseSchema.parse(value);
};
