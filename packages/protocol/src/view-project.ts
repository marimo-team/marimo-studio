import { z } from "zod";

import { mountDeclarationSchema } from "./projections.ts";
import { providerKeySchema } from "./provider-catalog.ts";
import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema, type JsonValue } from "./runtime-config.ts";
import { sourceDocumentPathSchema, sourceDocumentSchema } from "./source-documents.ts";
import { ownerGenerationSchema, viewNameSchema } from "./views.ts";

const canonicalMessageSchema = z
  .string()
  .min(1)
  .refine((value) => value.trim() === value, "Expected a canonical non-empty message");
const canonicalHintSchema = z
  .string()
  .refine((value) => value.trim() === value, "Expected a canonical hint");

export const projectSourceLocationSchema = z
  .object({
    path: sourceDocumentPathSchema,
    line: z.int().positive(),
    column: z.int().positive(),
  })
  .strict();

export const projectDiagnosticSchema = z
  .object({
    code: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
    severity: z.enum(["warning", "error"]),
    message: canonicalMessageSchema,
    hint: canonicalHintSchema,
    source: projectSourceLocationSchema.nullable(),
  })
  .strict();

export const viewBuildStateSchema = z
  .object({
    schema: z.literal(1),
    profile: z.enum(["development", "production"]),
    phase: z.enum(["unbuilt", "building", "failed", "published", "stale"]),
    project_revision: z.string().nullable(),
    artifact_revision: z.string().nullable(),
    diagnostics: z.array(projectDiagnosticSchema),
    duration_ms: z.int().nonnegative().nullable(),
  })
  .strict();

export const publishedArtifactSchema = z
  .object({
    profile: z.enum(["development", "production"]),
    input_id: z.string().min(1),
    artifact_id: z.string().min(1),
  })
  .strict();

export const viewProjectSchema = z
  .object({
    schema: z.literal(1),
    catalog_generation: ownerGenerationSchema,
    view_generation: ownerGenerationSchema,
    view: viewNameSchema,
    provider: providerKeySchema,
    provider_options: ownRecordSchema(z.string(), jsonValueSchema),
    documents: z.array(sourceDocumentSchema),
    mounts: z.array(mountDeclarationSchema),
    diagnostics: z.array(projectDiagnosticSchema),
    build: viewBuildStateSchema,
    artifact: publishedArtifactSchema.nullable(),
  })
  .strict()
  .superRefine((project, context) => {
    const paths = project.documents.map((document) => document.path);
    if (new Set(paths).size !== paths.length) {
      context.addIssue({
        code: "custom",
        path: ["documents"],
        message: "View project documents must have unique paths",
      });
    }
    const documents = new Set(paths);
    const diagnosticSources = new Set([...paths, "view.toml"]);
    const siteIds = project.mounts.map((site) => site.id);
    if (new Set(siteIds).size !== siteIds.length) {
      context.addIssue({
        code: "custom",
        path: ["mounts"],
        message: "View project mounts must have unique IDs",
      });
    }
    project.mounts.forEach((site, index) => {
      if (!sourceDocumentPathSchema.safeParse(site.source.path).success) {
        context.addIssue({
          code: "custom",
          path: ["mounts", index, "source", "path"],
          message: "Projection source paths must be normalized relative POSIX paths",
        });
      } else if (!documents.has(site.source.path)) {
        context.addIssue({
          code: "custom",
          path: ["mounts", index, "source", "path"],
          message: "Projection source paths must identify project documents",
        });
      }
    });
    project.diagnostics.forEach((diagnostic, index) => {
      const path = diagnostic.source?.path;
      if (path === undefined) {
        return;
      }
      if (!diagnosticSources.has(path)) {
        context.addIssue({
          code: "custom",
          path: ["diagnostics", index, "source", "path"],
          message: "Diagnostic source paths must identify project inputs",
        });
      }
    });
    project.build.diagnostics.forEach((diagnostic, index) => {
      const path = diagnostic.source?.path;
      if (path !== undefined && !diagnosticSources.has(path)) {
        context.addIssue({
          code: "custom",
          path: ["build", "diagnostics", index, "source", "path"],
          message: "Build diagnostic source paths must identify project inputs",
        });
      }
    });
    if (project.artifact !== null) {
      if (project.artifact.profile !== project.build.profile) {
        context.addIssue({
          code: "custom",
          path: ["artifact", "profile"],
          message: "The artifact profile must match the build profile",
        });
      }
    }
  });

export type ProjectSourceLocation = z.infer<typeof projectSourceLocationSchema>;
export type ProjectDiagnostic = z.infer<typeof projectDiagnosticSchema>;
export type ViewProject = z.infer<typeof viewProjectSchema>;
export type PublishedArtifact = z.infer<typeof publishedArtifactSchema>;
export type ViewBuildState = z.infer<typeof viewBuildStateSchema>;

export const parseViewProject = (payload: JsonValue): ViewProject =>
  viewProjectSchema.parse(payload);
