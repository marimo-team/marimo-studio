import { z } from "zod";

import {
  artifactSiteSchema,
  projectionPolicySchema,
  projectionTargetsSchema,
  runtimeBindingsSchema,
} from "./projections.ts";
import { ownRecordSchema } from "./records.ts";
import { resolveUrl } from "./url.ts";
import { viewNameSchema } from "./views.ts";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };

export const jsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.string(),
    z.number(),
    z.boolean(),
    z.null(),
    z.array(jsonValueSchema),
    ownRecordSchema(z.string(), jsonValueSchema),
  ]),
);
export const projectionDiagnosticSchema = z
  .object({
    code: z.string(),
    severity: z.enum(["warning", "error"]),
    message: z.string(),
    hint: z.string(),
    view: viewNameSchema,
    projection: z.enum(["cell", "value", "output"]),
    target: z.string(),
    source: z
      .object({
        path: z.string(),
        line: z.int(),
        column: z.int(),
      })
      .strict(),
    siteId: z.string().min(1).optional(),
  })
  .strict();

export type ProjectionDiagnostic = z.infer<typeof projectionDiagnosticSchema>;

export const runtimeIdSchema = z.string().regex(/^[a-z][a-z0-9-]*$/);
export const runtimeEnvelopeSchema = z
  .object({
    id: runtimeIdSchema,
    instance: z.string().min(1),
    data: ownRecordSchema(z.string(), z.unknown()),
    urls: ownRecordSchema(z.string(), z.string().min(1)),
  })
  .strict();

export type RuntimeEnvelope = z.infer<typeof runtimeEnvelopeSchema>;

const runtimeConfigFields = {
  schema: z.literal(1),
  revision: z.string(),
  projectionRevision: z.string().regex(/^[a-f0-9]{64}$/),
  view: viewNameSchema,
  views: z.array(viewNameSchema),
  runtime: runtimeEnvelopeSchema,
  rootUrl: z.string(),
  publicRootUrl: z.string(),
  documentRootUrl: z.string(),
  supportUrl: z.string(),
  presentationSessionId: z
    .string()
    .regex(/^s_[\da-z]{6}$/)
    .optional(),
  showCellLogs: z.boolean(),
  projectionTargets: projectionTargetsSchema,
  sites: z.array(artifactSiteSchema),
  projectionPolicy: projectionPolicySchema,
  runtimeBindings: runtimeBindingsSchema,
  diagnostics: z.array(projectionDiagnosticSchema),
  appConfig: ownRecordSchema(z.string(), z.unknown()),
  userConfig: ownRecordSchema(z.string(), z.unknown()),
  configOverrides: ownRecordSchema(z.string(), z.unknown()),
  dev: z.boolean(),
  mode: z.enum(["edit", "run"]),
};

const runtimeConfigSchema = z
  .object(runtimeConfigFields)
  .strict()
  .refine((config) => config.views.includes(config.view), {
    message: "The active view must be present in the view list.",
    path: ["view"],
  });
const mountConfigSchema = z
  .object({
    supportUrl: z.string(),
    version: z.string(),
    revision: z.string(),
    runtime: runtimeIdSchema,
    runtimeExplicit: z.boolean(),
    replay: z.boolean(),
    renewalToken: z.string().startsWith("d.").max(4096).optional(),
    clientId: z
      .string()
      .regex(/^[A-Za-z0-9_-]{16,128}$/)
      .optional(),
    lifecycleId: z.number().int().positive().max(Number.MAX_SAFE_INTEGER).optional(),
    runtimeSessionId: z
      .string()
      .regex(/^s_[\da-z]{6}$/)
      .optional(),
    sessionId: z
      .string()
      .regex(/^s_[\da-z]{6}$/)
      .optional(),
  })
  .strict()
  .superRefine((config, context) => {
    if (config.lifecycleId !== undefined && config.clientId === undefined) {
      context.addIssue({
        code: "custom",
        message: "A framed document lifecycle requires its client identity",
      });
    }
    if (config.runtime !== "server" && config.runtimeSessionId !== undefined) {
      context.addIssue({
        code: "custom",
        message: "Native session identity belongs to the server runtime",
      });
    }
    if (
      config.replay &&
      (config.runtime !== "server" || !config.runtimeSessionId || !config.renewalToken)
    ) {
      context.addIssue({
        code: "custom",
        message: "Replay requires server runtime and renewal authority",
      });
    }
  });

/** A runtime configuration whose URLs are absolute. */
export type RuntimeConfig = z.infer<typeof runtimeConfigSchema>;
/** A mount record whose support URL is absolute. */
export type MountConfig = z.infer<typeof mountConfigSchema>;

const resolveRuntimeConfigUrls = (config: RuntimeConfig, base: string | URL): RuntimeConfig => ({
  ...config,
  runtime: {
    ...config.runtime,
    urls: Object.fromEntries(
      Object.entries(config.runtime.urls).map(([name, url]) => [name, resolveUrl(url, base)]),
    ),
  },
  rootUrl: resolveUrl(config.rootUrl, base),
  publicRootUrl: resolveUrl(config.publicRootUrl, base),
  documentRootUrl: resolveUrl(config.documentRootUrl, base),
  supportUrl: resolveUrl(config.supportUrl, base),
});

/** Parse a runtime configuration and resolve its URLs against the carrier's URL. */
export const parseRuntimeConfig = (value: JsonValue, base: string | URL): RuntimeConfig =>
  resolveRuntimeConfigUrls(runtimeConfigSchema.parse(value), base);

/** Parse the mount record and resolve its support URL against the document base. */
export const parseMountConfig = (value: JsonValue, base: string | URL): MountConfig => {
  const mount = mountConfigSchema.parse(value);
  return { ...mount, supportUrl: resolveUrl(mount.supportUrl, base) };
};
