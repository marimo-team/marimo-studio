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
const runtimeDataSchema = z.strictObject({
  manifestUrl: z.string().min(1),
  planDigest: digestSchema,
});
const projectionMapSchema = (kind: "cell" | "output" | "value") =>
  losslessRecordSchema(boundedHostSelector, boundedOutputName(kind));
const studioManifestSchema = z.strictObject({
  schema: z.literal("marimo-studio.prepared.v1"),
  prepared: z.unknown(),
  projections: z.strictObject({
    cells: projectionMapSchema("cell"),
    outputs: projectionMapSchema("output"),
    values: projectionMapSchema("value"),
  }),
  document_sha256: digestSchema,
  view: z.string().min(1),
  plan_digest: digestSchema,
});

type UnparsedRuntimeData = Parameters<typeof runtimeDataSchema.safeParse>[0];
type UnparsedStudioManifest = Parameters<typeof studioManifestSchema.safeParse>[0];

export interface ZeroPythonRuntimeData {
  readonly manifestUrl: string;
  readonly planDigest: string;
}

export interface StudioProjectionBindings {
  readonly cells: Readonly<Record<string, string>>;
  readonly outputs: Readonly<Record<string, string>>;
  readonly values: Readonly<Record<string, string>>;
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

export const parseZeroPythonRuntimeData = (input: UnparsedRuntimeData): ZeroPythonRuntimeData => {
  const parsed = runtimeDataSchema.safeParse(input);
  if (!parsed.success) {
    throw new ZeroPythonRuntimeError("manifest_invalid", "Zero-Python runtime data is invalid.", {
      cause: parsed.error,
    });
  }
  return Object.freeze(parsed.data);
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
      cells: Object.freeze({ ...value.projections.cells }),
      outputs: Object.freeze({ ...value.projections.outputs }),
      values: Object.freeze({ ...value.projections.values }),
    }),
    documentSha256: value.document_sha256,
    view: value.view,
    planDigest: value.plan_digest,
  });
};

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
