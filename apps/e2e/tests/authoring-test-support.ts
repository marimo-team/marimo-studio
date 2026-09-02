import { studioBootstrapSchema } from "@marimo-studio/protocol/studio-bootstrap";
import { expect, type FrameLocator, type Page } from "@playwright/test";
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

export const readStudioBootstrap = async (page: Page) => {
  const source = await page.locator("#marimo-studio-bootstrap").textContent();
  if (!source) {
    throw new Error("Studio bootstrap is unavailable");
  }
  return studioBootstrapSchema.parse(JSON.parse(source));
};

export const studioClientId = async (page: Page): Promise<string> =>
  (await readStudioBootstrap(page)).clientId;

export const studioEditorSessionId = async (page: Page): Promise<string> => {
  const editorUrl = (await readStudioBootstrap(page)).urls.editor;
  const sessionId = new URL(editorUrl, "http://studio.invalid").searchParams.get("session_id");
  if (!sessionId) {
    throw new Error("Studio bootstrap editor URL is missing its session ID");
  }
  return sessionId;
};

export const executeCodeMode = async (
  editor: FrameLocator,
  file: string,
  sessionId: string,
  code: string,
): Promise<void> => {
  const result = await editor.locator("html").evaluate(
    async (_, request) => {
      const query = new URLSearchParams({ file: request.file });
      const response = await fetch(`api/kernel/execute?${query}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Session-Id": request.sessionId,
        },
        body: JSON.stringify({ code: request.code }),
      });
      return { ok: response.ok, text: await response.text() };
    },
    { code, file, sessionId },
  );
  expect(result.ok, result.text).toBe(true);
  expect(result.text).toContain('"success": true');
};

export const readBrowserValidation = (source: string) => {
  return browserValidationSchema.parse(JSON.parse(source));
};
