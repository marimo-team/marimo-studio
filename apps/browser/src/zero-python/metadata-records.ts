import type { PreparedExportManifest } from "@marimo-team/marimo-export/prepared";

import { losslessRecordSchema } from "@marimo-studio/presentation/json";
import { parsePreparedExportManifest } from "@marimo-team/marimo-export/prepared";
import { z } from "zod";

import { ZeroPythonRuntimeError } from "./errors.ts";

const digestSchema = z.string().regex(/^[\da-f]{64}$/u);
const encoder = new TextEncoder();
const boundedHostSelector = z.string().refine((value) => bounded(value, 1_024));
const boundedOutputName = (kind: "cell" | "output" | "value") =>
  z
    .string()
    .refine(
      (value) =>
        value.startsWith(`${kind}:`) && value.length > kind.length + 1 && bounded(value, 255),
    );
// A render reuses the page's export output when it reads a target in the
// same form, and otherwise names its own output with a digest of its source.
const boundedRenderOutputName = (kind: "cell" | "output" | "value") =>
  z
    .string()
    .refine(
      (value) => new RegExp(`^${kind}(?:@[\\da-f]{8})?:.`, "u").test(value) && bounded(value, 255),
    );
const zeroPythonRuntimeSchema = z.object({
  data: z.strictObject({ planDigest: digestSchema }),
  urls: z.strictObject({ manifest: z.string().min(1) }),
});
const projectionMapSchema = (kind: "cell" | "output" | "value") =>
  losslessRecordSchema(boundedHostSelector, boundedOutputName(kind));
const renderMapSchema = (kind: "cell" | "output" | "value") =>
  losslessRecordSchema(boundedHostSelector, boundedRenderOutputName(kind));
const renderBindingsSchema = z.strictObject({
  cells: renderMapSchema("cell"),
  outputs: renderMapSchema("output"),
  values: renderMapSchema("value"),
});
const studioManifestSchema = z.strictObject({
  schema: z.literal("marimo-studio.prepared.v1"),
  prepared: z.unknown(),
  projections: z.strictObject({
    cells: projectionMapSchema("cell"),
    outputs: projectionMapSchema("output"),
    values: projectionMapSchema("value"),
    renders: losslessRecordSchema(boundedHostSelector, renderBindingsSchema),
  }),
  document_sha256: digestSchema,
  view: z.string().min(1),
  plan_digest: digestSchema,
});

type UnparsedRuntimeEnvelope = Parameters<typeof zeroPythonRuntimeSchema.safeParse>[0];
type UnparsedStudioManifest = Parameters<typeof studioManifestSchema.safeParse>[0];

export interface ZeroPythonRuntimeData {
  readonly manifestUrl: string;
  readonly planDigest: string;
}

/** Export output names by target, for the page's hosts or one render's reads. */
export interface StudioTargetBindings {
  readonly cells: Readonly<Record<string, string>>;
  readonly outputs: Readonly<Record<string, string>>;
  readonly values: Readonly<Record<string, string>>;
}

export interface StudioProjectionBindings extends StudioTargetBindings {
  readonly renders: Readonly<Record<string, StudioTargetBindings>>;
}

export interface StudioPreparedManifest {
  readonly schema: "marimo-studio.prepared.v1";
  readonly prepared: PreparedExportManifest;
  readonly projections: StudioProjectionBindings;
  readonly documentSha256: string;
  readonly view: string;
  readonly planDigest: string;
}

export interface StudioPreparedContext {
  readonly planDigest: string;
  readonly view: string;
}

export const parseZeroPythonRuntimeData = (
  runtime: UnparsedRuntimeEnvelope,
): ZeroPythonRuntimeData => {
  const parsed = zeroPythonRuntimeSchema.safeParse(runtime);
  if (!parsed.success) {
    throw new ZeroPythonRuntimeError("manifest_invalid", "Prepared runtime data is invalid.", {
      cause: parsed.error,
    });
  }
  return Object.freeze({
    manifestUrl: parsed.data.urls.manifest,
    planDigest: parsed.data.data.planDigest,
  });
};

export const parseStudioPreparedManifest = (
  input: UnparsedStudioManifest,
): StudioPreparedManifest => {
  const parsed = studioManifestSchema.safeParse(input);
  if (!parsed.success) {
    throw new ZeroPythonRuntimeError("manifest_invalid", "Studio prepared metadata is invalid.", {
      cause: parsed.error,
    });
  }
  const value = parsed.data;
  return Object.freeze({
    schema: value.schema,
    prepared: parsePreparedExportManifest(value.prepared),
    projections: Object.freeze({
      ...frozenBindings(value.projections),
      renders: Object.freeze(
        Object.fromEntries(
          Object.entries(value.projections.renders).map(([render, bindings]) => [
            render,
            frozenBindings(bindings),
          ]),
        ),
      ),
    }),
    documentSha256: value.document_sha256,
    view: value.view,
    planDigest: value.plan_digest,
  });
};

const frozenBindings = (bindings: StudioTargetBindings): StudioTargetBindings =>
  Object.freeze({
    cells: Object.freeze({ ...bindings.cells }),
    outputs: Object.freeze({ ...bindings.outputs }),
    values: Object.freeze({ ...bindings.values }),
  });

const bounded = (value: string, maximumBytes: number): boolean =>
  value.length > 0 &&
  value === value.trim() &&
  !hasControl(value) &&
  !/[\ud800-\udfff]/u.test(value) &&
  encoder.encode(value).byteLength <= maximumBytes;

const hasControl = (value: string): boolean => {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return true;
  }
  return false;
};
