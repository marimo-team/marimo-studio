import { studioBootstrapSchema } from "@marimo-studio/protocol/studio-bootstrap";
import { expect, type Frame, type FrameLocator, type Page, type Request } from "@playwright/test";
import { z } from "zod";

import type { BrowserDiagnostics, BrowserResponseRecovery } from "./browser-diagnostics.ts";

import { projectionReadRequestKind } from "./projection-read-window.ts";

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

export const captureRetiringProjectionReads = (
  frame: Frame,
  revision: string,
  diagnostics: BrowserDiagnostics,
): BrowserResponseRecovery & { seal(): void } => {
  const page = frame.page();
  const origin = new URL(frame.url()).origin;
  const responses: BrowserResponseRecovery[] = [];
  const record = (request: Request) => {
    const url = new URL(request.url());
    if (!projectionReadRequestKind(request) || request.frame() !== frame || url.origin !== origin)
      return;
    let body: ReturnType<typeof viewRevisionSchema.safeParse>;
    try {
      body = viewRevisionSchema.safeParse(request.postDataJSON());
    } catch {
      return;
    }
    if (!body.success || body.data.revision !== revision) return;
    responses.push(
      diagnostics.expectResponse({
        status: 409,
        path: new RegExp(`^${RegExp.escape(url.pathname)}$`),
        required: false,
      }),
    );
  };
  const seal = () => {
    page.off("request", record);
    page.off("close", seal);
  };
  page.on("request", record);
  page.once("close", seal);
  return {
    seal,
    recovered: () => {
      seal();
      responses.forEach((response) => response.recovered());
    },
  };
};

// The unsaved native page can retire its save response during navigation.
// Recover only after the saved file and original session have been verified.
export const expectFirstSaveRetirement = (
  diagnostics: BrowserDiagnostics,
  origin: string,
): BrowserResponseRecovery => {
  const request = diagnostics.expectRequestFailure({
    origin,
    method: "POST",
    path: /^\/api\/kernel\/save$/,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  const error = diagnostics.expectConsole({
    type: "error",
    text: /^Failed to handle request: sendSave TypeError: Failed to fetch(?:\n|$)/,
    required: false,
  });
  return {
    recovered: () => {
      request.recovered();
      error.recovered();
    },
  };
};
