import { expect, test as base, type FrameLocator, type Page } from "@playwright/test";
import { execFile as execFileCallback } from "node:child_process";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { z } from "zod";

import {
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  notebookPath,
  repositoryDirectory,
  workspaceDirectory,
} from "../scripts/paths.mjs";

const execFile = promisify(execFileCallback);
const dashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/notebook/dashboard");
const plainDashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/plain/dashboard");
const plainReportDirectory = resolve(workspaceDirectory, "__marimo__/studio/plain/report");

export const dashboardHtmlPath = resolve(dashboardDirectory, "index.html");
export const dashboardCssPath = resolve(dashboardDirectory, "app.css");
export const plainDashboardHtmlPath = resolve(plainDashboardDirectory, "index.html");
export const plainReportHtmlPath = resolve(plainReportDirectory, "index.html");
export const plainNotebookPath = resolve(workspaceDirectory, "plain.py");
export const workspaceNotebookPath = notebookPath;
export const hostedDashboardHtmlPath = resolve(
  hostedWorkspaceDirectory,
  "__marimo__/studio/notebook/dashboard/index.html",
);
export const hostedViewFixturePath = resolve(hostedFixtureDirectory, "dashboard.html");
export const studioEntryUrl = "/?file=notebook.py";

const workspaceCheckSchema = z.object({ ok: z.boolean() });
const workspaceAnalysisSchema = z.object({
  actions: z.array(z.record(z.string(), z.json())),
  handoff_ready: z.boolean(),
});
const sessionAdminBootstrapSchema = z.object({
  serverToken: z.string(),
  urls: z.object({ query: z.string() }),
});
const sessionInventorySchema = z.object({
  files: z.array(z.object({ sessionId: z.string() })),
});

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
  await copyFixtureFile("plain.py");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/index.html");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/app.css");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/scripts/app.js");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/scripts/message.js");
  await rm(resolve(workspaceDirectory, "__marimo__/studio/notebook/qa-view"), {
    force: true,
    recursive: true,
  });
  await rm(resolve(workspaceDirectory, "__marimo__/studio/plain"), {
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

const runStudioCli = (args: string[]) =>
  execFile("uv", ["run", "--frozen", "--project", repositoryDirectory, "marimo-studio", ...args], {
    cwd: repositoryDirectory,
  });

export const bindWorkspaceCell = (alias: string, cell: number) =>
  runStudioCli(["bind", workspaceNotebookPath, "--cell", String(cell), "--as", alias]);

export const addWorkspaceView = (target: string, name: string) =>
  runStudioCli(["view", "add", target, "--name", name]);

export const checkWorkspace = async (): Promise<boolean> => {
  const { stdout } = await runStudioCli(["check", workspaceNotebookPath, "--format", "json"]);
  return workspaceCheckSchema.parse(JSON.parse(stdout)).ok;
};

declare global {
  var __e2eRuntimeMarker: string | undefined;
}

export const analyzeWorkspace = async (view: string) => {
  const { stdout } = await runStudioCli([
    "analyze",
    workspaceNotebookPath,
    "--view",
    view,
    "--server",
    "http://127.0.0.1:4321?file=notebook.py",
    "--format",
    "json",
  ]);
  return workspaceAnalysisSchema.parse(JSON.parse(stdout));
};

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
            if (!globalThis.marimoStudio) {
              return false;
            }
            return Promise.race([
              globalThis.marimoStudio.ready().then(() => true),
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
  const bootstrapElement = page.locator("#marimo-studio-bootstrap");
  if ((await bootstrapElement.count()) === 0) {
    return undefined;
  }
  const source = await bootstrapElement.textContent().catch(() => null);
  if (!source) {
    return undefined;
  }
  const bootstrap = sessionAdminBootstrapSchema.parse(JSON.parse(source));
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

export const studioServerToken = async (page: Page): Promise<string> => {
  const admin = await sessionAdmin(page);
  if (!admin) {
    throw new Error("Studio session administration is unavailable");
  }
  return admin.serverToken;
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
  const inventory = sessionInventorySchema.parse(await running.json());
  for (const file of inventory.files) {
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
        const missingProjectedControl = message.text().includes("UIElementRegistry missing entry");
        const nativeLanguageServerTimeout =
          message.location().url.includes("/_marimo-studio/editor/assets/") &&
          message.text().startsWith("Language server initialization failed") &&
          message.text().includes('Request "initialize" timed out');
        if (
          missingProjectedControl ||
          (message.type() === "error" &&
            !nativeLanguageServerTimeout &&
            !message.text().startsWith("Failed to load resource:"))
        ) {
          const source = message.location().url;
          messages.push(`console${source ? ` (${source})` : ""}: ${message.text()}`);
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
        const transientActivation =
          response.status() === 409 &&
          /^\/_marimo-studio\/activations\/\d+\/ack$/.test(url.pathname);
        if (response.status() >= 400 && !transientConfig && !transientActivation) {
          messages.push(`http ${response.status()}: ${response.url()}`);
        }
      });

      await use({ messages });

      const hosted = page.url().startsWith("http://127.0.0.1:4322/");
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
        if (hosted) {
          await restoreHostedWorkspace();
        } else {
          await restoreWorkspace();
        }
      }
    },
    { auto: true },
  ],
});

test.beforeEach(async () => {
  await restoreWorkspace();
});

export { expect };
