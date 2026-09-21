import { studioBootstrapSchema } from "@marimo-studio/protocol/studio-bootstrap";
import { expect, type FrameLocator, type Page } from "@playwright/test";
import { z } from "zod";

export const saveShortcut = process.platform === "darwin" ? "Meta+s" : "Control+s";
// Marimo also supports Ctrl+Enter on macOS.
export const runCellShortcut = "Control+Enter";
export const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";

const viewRevisionSchema = z.object({ revision: z.string() });

export const readViewRevision = (source: string): string => {
  return viewRevisionSchema.parse(JSON.parse(source)).revision;
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
  editor: FrameLocator | Page,
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
