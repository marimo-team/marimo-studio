import { expect, test as base, type FrameLocator, type Page } from "@playwright/test";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  notebookPath,
  workspaceDirectory,
} from "../scripts/paths.mjs";

const dashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/notebook/dashboard");

export const dashboardHtmlPath = resolve(dashboardDirectory, "index.html");
export const dashboardCssPath = resolve(dashboardDirectory, "app.css");
export const workspaceNotebookPath = notebookPath;
export const hostedDashboardHtmlPath = resolve(
  hostedWorkspaceDirectory,
  "__marimo__/studio/notebook/dashboard/index.html",
);
export const hostedViewFixturePath = resolve(hostedFixtureDirectory, "dashboard.html");

const copyFixtureFile = async (relativePath: string) => {
  const source = resolve(fixtureDirectory, relativePath);
  const target = resolve(workspaceDirectory, relativePath);
  const expected = await readFile(source);
  const current = await readFile(target).catch(() => null);
  if (current?.equals(expected)) {
    return;
  }
  await mkdir(resolve(target, ".."), { recursive: true });
  await cp(source, target, { force: true });
};

export const restoreWorkspace = async () => {
  await copyFixtureFile("notebook.py");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/index.html");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/app.css");
  await rm(resolve(workspaceDirectory, "__marimo__/studio/notebook/qa-view"), {
    force: true,
    recursive: true,
  });
};

export const restoreHostedWorkspace = async () => {
  for (const relativePath of ["notebook.py", "pyproject.toml", "dashboard.html"]) {
    const source = resolve(hostedFixtureDirectory, relativePath);
    const target = resolve(hostedWorkspaceDirectory, relativePath);
    await mkdir(resolve(target, ".."), { recursive: true });
    await cp(source, target, { force: true });
  }
  await rm(resolve(hostedWorkspaceDirectory, "__marimo__"), {
    force: true,
    recursive: true,
  });
};

export const hostedWorkspaceNotebookPath = hostedNotebookPath;

export const readWorkspaceFile = (path: string) => readFile(path, "utf8");
export const writeWorkspaceFile = (path: string, content: string) => writeFile(path, content);

export const editorFrame = (page: Page): FrameLocator =>
  page.frameLocator('iframe[title="Marimo editor"]');

export const editorSlider = (page: Page) => editorFrame(page).getByRole("slider");

export const previewFrame = (page: Page, runtime = "server"): FrameLocator =>
  page.frameLocator(`iframe[data-preview-runtime-frame="${runtime}"]`);

export const waitForPreview = async (page: Page, runtime = "server") => {
  const frame = page.locator(`iframe[data-preview-runtime-frame="${runtime}"]`);
  await expect(frame).toBeAttached();
  const preview = previewFrame(page, runtime);
  await expect
    .poll(
      () =>
        preview
          .locator("html")
          .evaluate(async () => {
            const studio = globalThis as typeof globalThis & {
              marimoStudio?: { ready: () => Promise<void> };
            };
            if (!studio.marimoStudio) {
              return false;
            }
            return Promise.race([
              studio.marimoStudio.ready().then(() => true),
              new Promise<false>((resolve) => setTimeout(() => resolve(false), 500)),
            ]);
          })
          .catch(() => false),
      { timeout: 30_000 },
    )
    .toBe(true);
  return preview;
};

type BrowserDiagnostics = {
  messages: string[];
};

interface SessionAdmin {
  apiRoot: string;
  serverToken: string;
}

const sessionAdmin = async (page: Page): Promise<SessionAdmin | undefined> => {
  if (page.isClosed()) {
    return undefined;
  }
  const source = await page
    .locator("#marimo-studio-bootstrap")
    .textContent()
    .catch(() => null);
  if (!source) {
    return undefined;
  }
  const bootstrap: unknown = JSON.parse(source);
  if (
    typeof bootstrap !== "object" ||
    bootstrap === null ||
    !("serverToken" in bootstrap) ||
    typeof bootstrap.serverToken !== "string" ||
    !("urls" in bootstrap) ||
    typeof bootstrap.urls !== "object" ||
    bootstrap.urls === null ||
    !("query" in bootstrap.urls) ||
    typeof bootstrap.urls.query !== "string"
  ) {
    throw new TypeError("Studio bootstrap is missing session administration fields");
  }
  const query = new URL(bootstrap.urls.query, page.url());
  const queryPath = "/_marimo-studio/query";
  if (!query.pathname.endsWith(queryPath)) {
    throw new TypeError(`Unexpected Studio query URL ${query.pathname}`);
  }
  return {
    apiRoot: new URL(`${query.pathname.slice(0, -queryPath.length)}/api/home`, query.origin).href,
    serverToken: bootstrap.serverToken,
  };
};

const closeNotebookSessions = async (page: Page): Promise<void> => {
  const admin = await sessionAdmin(page);
  const request = page.request;
  await page.close();
  if (!admin) {
    return;
  }
  const headers = { "Marimo-Server-Token": admin.serverToken };
  const running = await request.post(`${admin.apiRoot}/running_notebooks`, { headers });
  if (!running.ok()) {
    throw new Error(`Could not list Marimo sessions: ${running.status()}`);
  }
  const payload: unknown = await running.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("files" in payload) ||
    !Array.isArray(payload.files)
  ) {
    throw new TypeError("Marimo returned an invalid session inventory");
  }
  for (const file of payload.files) {
    if (
      typeof file !== "object" ||
      file === null ||
      !("sessionId" in file) ||
      typeof file.sessionId !== "string"
    ) {
      throw new TypeError("Marimo returned an invalid session record");
    }
    const closed = await request.post(`${admin.apiRoot}/shutdown_session`, {
      data: { sessionId: file.sessionId },
      headers,
    });
    if (!closed.ok()) {
      throw new Error(`Could not close Marimo session: ${closed.status()}`);
    }
  }
};

export const test = base.extend<{ browserDiagnostics: BrowserDiagnostics }>({
  browserDiagnostics: [
    async ({ page }, use, testInfo) => {
      const messages: string[] = [];
      page.on("pageerror", (error) => messages.push(`pageerror: ${error.message}`));
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) {
          messages.push(`console: ${message.text()}`);
        }
      });
      page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText ?? "unknown error";
        if (failure !== "net::ERR_ABORTED") {
          messages.push(`request failed: ${request.url()} (${failure})`);
        }
      });
      page.on("response", (response) => {
        const url = new URL(response.url());
        const transientConfig =
          response.status() === 409 &&
          url.pathname.includes("/_marimo-studio/views/") &&
          url.pathname.endsWith("/config");
        if (response.status() >= 400 && !transientConfig) {
          messages.push(`http ${response.status()}: ${response.url()}`);
        }
      });

      await use({ messages });

      try {
        if (messages.length > 0 || testInfo.status !== testInfo.expectedStatus) {
          await testInfo.attach("browser-diagnostics", {
            body: Buffer.from(messages.join("\n") || "No browser errors recorded."),
            contentType: "text/plain",
          });
          if (!page.isClosed()) {
            await testInfo.attach("studio-document", {
              body: Buffer.from(await page.content()),
              contentType: "text/html",
            });
          }
        }
        expect(messages, "unexpected browser diagnostics").toEqual([]);
      } finally {
        await closeNotebookSessions(page);
        await restoreWorkspace();
      }
    },
    { auto: true },
  ],
});

test.beforeEach(async () => {
  await restoreWorkspace();
});

export { expect };
