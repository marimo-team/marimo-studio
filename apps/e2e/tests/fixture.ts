import { expect, test as base, type FrameLocator, type Page } from "@playwright/test";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { fixtureDirectory, notebookPath, workspaceDirectory } from "../scripts/paths.mjs";

const dashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/notebook/dashboard");

export const dashboardHtmlPath = resolve(dashboardDirectory, "index.html");
export const dashboardCssPath = resolve(dashboardDirectory, "app.css");
export const workspaceNotebookPath = notebookPath;

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
          url.pathname.startsWith("/_marimo-studio/views/") &&
          url.pathname.endsWith("/config");
        if (response.status() >= 400 && !transientConfig) {
          messages.push(`http ${response.status()}: ${response.url()}`);
        }
      });

      await use({ messages });

      if (messages.length > 0 || testInfo.status !== testInfo.expectedStatus) {
        await testInfo.attach("browser-diagnostics", {
          body: Buffer.from(messages.join("\n") || "No browser errors recorded."),
          contentType: "text/plain",
        });
        await testInfo.attach("studio-document", {
          body: Buffer.from(await page.content()),
          contentType: "text/html",
        });
      }
      expect(messages, "unexpected browser diagnostics").toEqual([]);
    },
    { auto: true },
  ],
});

test.beforeEach(async () => {
  await restoreWorkspace();
});

test.afterEach(async () => {
  await restoreWorkspace();
});

export { expect };
