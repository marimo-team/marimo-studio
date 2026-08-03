import { z } from "zod";

export const jsonValueSchema = z.json();
export const cellBindingConfigSchema = z.object({
  kind: z.enum(["id", "name"]),
  value: z.string(),
});
export const valueBindingConfigSchema = z.object({
  variable: z.string(),
  cell: cellBindingConfigSchema,
});
export const projectionDiagnosticSchema = z.object({
  code: z.string(),
  severity: z.enum(["warning", "error"]),
  message: z.string(),
  hint: z.string(),
  view: z.string(),
  projection: z.enum(["cell", "value"]),
  target: z.string(),
  source: z.object({
    path: z.string(),
    line: z.int(),
    column: z.int(),
  }),
});

export type JsonValue = z.infer<typeof jsonValueSchema>;
export type CellBindingConfig = z.infer<typeof cellBindingConfigSchema>;
export type ValueBindingConfig = z.infer<typeof valueBindingConfigSchema>;
export type ProjectionDiagnostic = z.infer<typeof projectionDiagnosticSchema>;

const runtimeConfigFields = {
  schema: z.literal(1),
  revision: z.string(),
  view: z.string(),
  views: z.array(z.string()),
  fileKey: z.string(),
  runtimeUrl: z.string(),
  supportUrl: z.string(),
  cellBindings: z.record(z.string(), cellBindingConfigSchema),
  valueBindings: z.record(z.string(), valueBindingConfigSchema),
  diagnostics: z.array(projectionDiagnosticSchema),
  appConfig: z.record(z.string(), z.unknown()),
  userConfig: z.record(z.string(), z.unknown()),
  configOverrides: z.record(z.string(), z.unknown()),
  serverToken: z.string(),
  dev: z.boolean(),
  mode: z.enum(["edit", "run"]),
  preserveSession: z.boolean(),
};

export const runtimeConfigSchema = z
  .object(runtimeConfigFields)
  .refine((config) => config.views.includes(config.view), {
    message: "The active view must be present in the view list.",
    path: ["view"],
  });
export const mountConfigSchema = z.object({
  supportUrl: z.string(),
  version: z.string(),
  revision: z.string(),
});

export type RuntimeConfig = z.infer<typeof runtimeConfigSchema>;
export type MountConfig = z.infer<typeof mountConfigSchema>;

export const parseRuntimeConfig = (value: unknown): RuntimeConfig => {
  return runtimeConfigSchema.parse(value);
};

export const parseMountConfig = (value: unknown): MountConfig => {
  return mountConfigSchema.parse(value);
};
