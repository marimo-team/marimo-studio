import { studioBootstrapSchema } from "@marimo-studio/protocol/studio-bootstrap";
import { z } from "zod";

export const saveShortcut = process.platform === "darwin" ? "Meta+s" : "Control+s";
export const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";

export const observationStateSchema = z.enum([
  "error",
  "loading",
  "not-observed",
  "ready",
  "stale",
]);
export const projectionInstanceSchema = z.object({
  mount_id: z.string().min(1),
  instance_id: z.string().min(1),
  target: z.string(),
  runtime_cell_id: z.string().min(1),
  phase: z.literal("ready"),
  error: z.null(),
});
export const projectionEvidenceFields = {
  projection_instances: z.array(projectionInstanceSchema).default([]),
};
export const viewRevisionSchema = z.object({ revision: z.string() });
export const requestedObservationsSchema = z.object({
  observations: z
    .array(
      z.object({
        diagnostics: z.array(z.record(z.string(), z.json())),
        revision: z.string().optional(),
        state: observationStateSchema,
        view: z.string(),
        ...projectionEvidenceFields,
      }),
    )
    .min(1),
});
export const changedObservationSourceSchema = z.object({
  error: z.literal("validation-source-changed"),
});
export const browserValidationSchema = z.object({
  ok: z.boolean(),
  stages: z.object({
    browser: z.object({
      observations: z
        .array(
          z.object({
            client_id: z.string().optional(),
            runtime_instance: z.string().optional(),
            session_id: z.string().optional(),
            state: observationStateSchema,
            ...projectionEvidenceFields,
          }),
        )
        .min(1),
    }),
  }),
});
export const readViewRevision = (source: string): string => {
  return viewRevisionSchema.parse(JSON.parse(source)).revision;
};

export const readRequestedObservation = (source: string) => {
  return requestedObservationsSchema.parse(JSON.parse(source)).observations[0];
};

export const readStudioClientId = (source: string): string => {
  return studioBootstrapSchema.parse(JSON.parse(source)).clientId;
};

export const readStudioEditorSessionId = (source: string): string => {
  const editorUrl = studioBootstrapSchema.parse(JSON.parse(source)).urls.editor;
  const sessionId = new URL(editorUrl, "http://studio.invalid").searchParams.get("session_id");
  if (!sessionId) {
    throw new Error("Studio bootstrap editor URL is missing its session ID");
  }
  return sessionId;
};

export const readBrowserValidation = (source: string) => {
  return browserValidationSchema.parse(JSON.parse(source));
};
