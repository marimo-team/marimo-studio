import { viewListSchema } from "@marimo-studio/protocol/views";
import {
  expect,
  test as base,
  type APIRequestContext,
  type FrameLocator,
  type Locator,
  type Page,
} from "@playwright/test";
import { execFile as execFileCallback } from "node:child_process";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { z } from "zod";

import { prepareCollaborativeWorkspace } from "../scripts/collaborative-workspace.mjs";
import { e2eNetwork } from "../scripts/network.mjs";
import {
  collaborativeWorkspaceDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  notebookPath,
  noDisplayNotebookPath,
  noDisplayStaticExportDirectory,
  repositoryDirectory,
  workspaceDirectory,
} from "../scripts/paths.mjs";
import {
  observeBrowserContext,
  type BrowserDiagnostics,
  type BrowserDiagnosticsScope,
  type ProjectionRefreshCapture,
  type RequestAbortCapture,
  type ResponseTransitionCapture,
  type WorkspaceEventStreamCapture,
} from "./browser-diagnostics.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

export {
  expectSupersededRenewalConfig,
  observeBrowserContext,
  type BrowserActiveRequestAbortExpectation,
  type BrowserConsoleExpectation,
  type BrowserDiagnostics,
  type BrowserDiagnosticsScope,
  type BrowserRequestAbortExpectation,
  type BrowserRequestFailureExpectation,
  type BrowserResponseExpectation,
  type BrowserResponseTransitionExpectation,
  type BrowserResponseRecovery,
  type HeldRequestAbortCapture,
  type ProjectionRefreshCapture,
  type RequestAbortCapture,
  type ResponseTransitionCapture,
  type WorkspaceEventStreamCapture,
} from "./browser-diagnostics.ts";

const execFile = promisify(execFileCallback);
const dashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/notebook/dashboard");
const collaborativeDashboardDirectory = resolve(
  collaborativeWorkspaceDirectory,
  "__marimo__/studio/notebook/dashboard",
);
const collaborativeNotebookPath = resolve(collaborativeWorkspaceDirectory, "notebook.py");
const plainDashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/plain/dashboard");
const plainReportDirectory = resolve(workspaceDirectory, "__marimo__/studio/plain/report");
const removeTree = (path: string) =>
  rm(path, {
    force: true,
    maxRetries: 20,
    recursive: true,
    retryDelay: 25,
  });

export const dashboardHtmlPath = resolve(dashboardDirectory, "src/index.html");
export const dashboardCssPath = resolve(dashboardDirectory, "src/app.css");
export const dashboardManifestPath = resolve(dashboardDirectory, "view.toml");
export const collaborativeDashboardHtmlPath = resolve(
  collaborativeDashboardDirectory,
  "src/index.html",
);
export const collaborativeCreatedViewHtmlPath = (view: string) =>
  resolve(collaborativeWorkspaceDirectory, "__marimo__/studio/notebook", view, "index.html");
export const workspaceCreatedViewHtmlPath = (view: string) =>
  resolve(workspaceDirectory, "__marimo__/studio/notebook", view, "index.html");
export const plainDashboardHtmlPath = resolve(plainDashboardDirectory, "index.html");
export const plainReportHtmlPath = resolve(plainReportDirectory, "index.html");
export const plainNotebookPath = resolve(workspaceDirectory, "plain.py");
export const workspaceNotebookPath = notebookPath;
export const workspaceNoDisplayNotebookPath = noDisplayNotebookPath;
export const workspaceNoDisplayStaticExportPath = noDisplayStaticExportDirectory;
export const hostedDashboardHtmlPath = resolve(
  hostedWorkspaceDirectory,
  "__marimo__/studio/notebook/dashboard/index.html",
);
export const hostedViewFixturePath = resolve(hostedFixtureDirectory, "dashboard.html");
export const studioOrigin = e2eNetwork.main.studio.origin;
export const hostedOrigin = e2eNetwork.main.hosted.origin;
export const studioEntryUrl = "/?file=notebook.py";
export const collaborativeStudioEntryUrl = `${e2eNetwork.main.collaboration.origin}/?file=notebook.py`;
export const staticExportUrl = `${e2eNetwork.main.exported.origin}/src/index.html`;
export const noDisplayStaticExportUrl = `${e2eNetwork.main.exported.origin}/no-display/index.html`;

const workspaceCheckSchema = z.object({ ok: z.boolean() });
const workspaceShowSchema = z.object({
  schema: z.literal(1),
  notebook: z.string(),
  view: z.string(),
  generation: z.number().int().positive(),
  client_id: z.string(),
  session_id: z.string(),
});
const sessionAdminBootstrapSchema = z.object({
  serverToken: z.string(),
  urls: z.object({ views: z.string() }),
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
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/notebook"));
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/no-display"));
  await copyFixtureFile("notebook.py");
  await copyFixtureFile("no-display.py");
  await removeTree(noDisplayStaticExportDirectory);
  await copyFixtureFile("plain.py");
  await rm(resolve(workspaceDirectory, "first-save.py"), { force: true });
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/view.toml");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/index.html");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/app.css");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/scripts/app.js");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/scripts/message.js");
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/plain"));
};

export const restoreHostedWorkspace = async () => {
  for (const relativePath of ["notebook.py", "dashboard.html"]) {
    const source = resolve(hostedFixtureDirectory, relativePath);
    const target = resolve(hostedWorkspaceDirectory, relativePath);
    await mkdir(resolve(target, ".."), { recursive: true });
    await cp(source, target, { force: true });
  }
  await removeTree(resolve(hostedWorkspaceDirectory, "__marimo__"));
};

export const hostedWorkspaceNotebookPath = hostedNotebookPath;

export const readWorkspaceFile = (path: string) => readFile(path, "utf8");
export const writeWorkspaceFile = (path: string, content: string) => writeFile(path, content);

const runStudioCli = (args: string[]) =>
  execFile("uv", ["run", "--frozen", "--group", "e2e", "marimo-studio", ...args], {
    cwd: repositoryDirectory,
  });

export const bindWorkspaceCell = (alias: string, cell: number) =>
  runStudioCli([
    "notebook",
    "bind",
    alias,
    "--target",
    workspaceNotebookPath,
    "--cell",
    String(cell),
  ]);

export const addWorkspaceView = (target: string, name: string, starter?: string) =>
  runStudioCli([
    "view",
    "create",
    name,
    "--target",
    target,
    ...(starter ? ["--starter", starter] : []),
  ]);

export const buildWorkspaceView = (name: string, target = workspaceNotebookPath) =>
  runStudioCli(["view", "build", name, "--target", target, "--profile", "development"]);

export const exportWorkspaceView = (name: string, target: string, output: string) =>
  runStudioCli(["view", "export", name, "--target", target, "--output", output]);

export const addCollaborativeView = (name: string) =>
  runStudioCli(["view", "create", name, "--target", collaborativeNotebookPath]);

export const activateWorkspaceView = async (view: string, browserClient?: string) => {
  const args = [
    "view",
    "show",
    view,
    "--target",
    workspaceNotebookPath,
    "--server",
    `${studioOrigin}?file=notebook.py`,
    "--json",
  ];
  if (browserClient) {
    args.push("--browser-client", browserClient);
  }
  const { stdout } = await runStudioCli(args);
  return workspaceShowSchema.parse(JSON.parse(stdout));
};

export const checkWorkspace = async (): Promise<boolean> => {
  const { stdout } = await runStudioCli(["validate", "--target", workspaceNotebookPath, "--json"]);
  return workspaceCheckSchema.parse(JSON.parse(stdout)).ok;
};

declare global {
  var __e2eRuntimeMarker: string | undefined;
}

export const editorFrame = (page: Page): FrameLocator =>
  page.frameLocator('iframe[title="Marimo editor"]');

export const labeledSlider = (root: FrameLocator | Locator, label: RegExp | string): Locator =>
  root.locator("marimo-slider").filter({ hasText: label }).getByRole("slider");

export const editorSlider = (page: Page, label: RegExp | string = /^Scale/) =>
  labeledSlider(editorFrame(page), label);

export const presentationFrame = (page: Page): FrameLocator =>
  page.frameLocator("iframe#marimo-studio-presentation");

export const previewFrame = (page: Page, runtime = "server"): FrameLocator =>
  page.frameLocator(`iframe[data-preview-runtime-frame="${runtime}"]`);

const waitForPreviewFrame = async (page: Page, selector: string, timeout = 65_000) => {
  const frame = page.locator(selector);
  await expect(frame).toBeAttached({ timeout });
  const preview = page.frameLocator(selector);
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
      { timeout },
    )
    .toBe(true);
  await expect(frame).not.toHaveAttribute("inert", { timeout });
  await expect(frame).not.toHaveAttribute("aria-busy", { timeout });
  return preview;
};

export const waitForPreview = async (page: Page, runtime = "server") =>
  waitForPreviewFrame(page, `iframe[data-preview-runtime-frame="${runtime}"]`);

export const waitForViewPreview = async (
  page: Page,
  view: string,
  runtime = "server",
  timeout = 65_000,
) =>
  waitForPreviewFrame(
    page,
    `iframe[data-preview-view-frame="${view}"][data-preview-runtime-frame="${runtime}"]`,
    timeout,
  );

interface ProjectionRefreshScope {
  readonly capture: ProjectionRefreshCapture;
  readonly initialRevision: string;
}

const projectionRevision = (preview: FrameLocator): Promise<string> =>
  preview.locator("html").evaluate(() => globalThis.marimoStudio.identity().projectionRevision);

export const captureProjectionRefresh = async (
  page: Page,
  diagnostics: BrowserDiagnostics,
): Promise<ProjectionRefreshScope> => {
  const preview = previewFrame(page);
  const frameElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const frame = await frameElement?.contentFrame().finally(() => frameElement.dispose());
  if (frame === null || frame === undefined) {
    throw new Error("The server preview frame is unavailable.");
  }
  const initialRevision = await projectionRevision(preview);
  return {
    capture: diagnostics.expectProjectionRefresh(frame, initialRevision),
    initialRevision,
  };
};

export const recoverProjectionRefresh = async (
  scope: ProjectionRefreshScope,
  page: Page,
): Promise<void> => {
  const preview = previewFrame(page);
  await expect
    .poll(() => projectionRevision(preview), { timeout: 65_000 })
    .not.toBe(scope.initialRevision);
  scope.capture.seal();
  let currentProjectionRevision = scope.initialRevision;
  await expect
    .poll(
      async () => {
        currentProjectionRevision = await projectionRevision(preview);
        return scope.capture.ready(currentProjectionRevision);
      },
      { timeout: 65_000 },
    )
    .toBe(true);
  if (!scope.capture.recovered(currentProjectionRevision)) {
    throw new Error("The projection refresh changed while recovery was committing.");
  }
  scope.capture.dispose();
};

export const recoverRequestAbort = async (capture: RequestAbortCapture): Promise<void> => {
  capture.seal();
  await expect.poll(() => capture.ready(), { timeout: 10_000 }).toBe(true);
  if (!capture.recovered()) {
    throw new Error("The request abort changed while recovery was committing.");
  }
};

export const recoverResponseTransition = async (
  capture: ResponseTransitionCapture,
): Promise<void> => {
  await expect.poll(() => capture.ready(), { timeout: 10_000 }).toBe(true);
  if (!capture.recovered()) {
    throw new Error("The response transition changed while recovery was committing.");
  }
};

export const recoverWorkspaceEventStream = async (
  capture: WorkspaceEventStreamCapture,
): Promise<void> => {
  await expect.poll(() => capture.ready(), { timeout: 10_000 }).toBe(true);
  capture.recovered();
};

interface SessionAdmin {
  apiRoot: string;
  serverToken: string;
  viewsUrl: string;
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
  const views = new URL(bootstrap.urls.views, page.url());
  const viewsPath = "/_marimo-studio/views";
  if (!views.pathname.endsWith(viewsPath)) {
    throw new TypeError(`Unexpected Studio views URL ${views.pathname}`);
  }
  return {
    apiRoot: new URL(`${views.pathname.slice(0, -viewsPath.length)}/api/home`, views.origin).href,
    serverToken: bootstrap.serverToken,
    viewsUrl: views.href,
  };
};

export const studioServerToken = async (page: Page): Promise<string> => {
  const admin = await sessionAdmin(page);
  if (!admin) {
    throw new Error("Studio session administration is unavailable");
  }
  return admin.serverToken;
};

export const writeViewSource = async (
  page: Page,
  view: string,
  path: string,
  content: string,
  file = "notebook.py",
): Promise<void> => {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  const url = `/_marimo-studio/views/${encodeURIComponent(view)}/source/${encoded}?file=${encodeURIComponent(file)}`;
  const current = await page.request.get(url);
  const revision = current.headers().etag;
  if (!current.ok() || !revision) {
    throw new Error(`Could not load dashboard source (${current.status()})`);
  }
  const saved = await page.request.put(url, {
    data: content,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "If-Match": revision,
      "Marimo-Server-Token": await studioServerToken(page),
    },
  });
  if (!saved.ok()) {
    throw new Error(`Could not save ${view} source (${saved.status()}): ${await saved.text()}`);
  }
};

export const writeDashboardSource = async (page: Page, content: string): Promise<void> =>
  writeViewSource(page, "dashboard", "src/index.html", content);

export const removeWorkspaceView = async (
  page: Page,
  view: string,
  file = "notebook.py",
): Promise<void> => {
  const response = await page.request.delete(
    `/_marimo-studio/views/${encodeURIComponent(view)}?file=${encodeURIComponent(file)}`,
    { headers: { "Marimo-Server-Token": await studioServerToken(page) } },
  );
  if (!response.ok()) {
    throw new Error(`Could not remove ${view} (${response.status()}): ${await response.text()}`);
  }
};

const releaseWindowsWorkspaceProjects = async (
  request: APIRequestContext,
  admin: SessionAdmin,
): Promise<void> => {
  if (process.platform !== "win32") {
    return;
  }
  const headers = { "Marimo-Server-Token": admin.serverToken };
  const response = await request.get(admin.viewsUrl);
  if (!response.ok()) {
    throw new Error(`Could not inspect Studio views: ${response.status()}`);
  }
  const inventory = viewListSchema.parse(await response.json());
  const survivor = "windows-cleanup";
  if (!inventory.views.some(({ name }) => name === survivor)) {
    const created = await request.post(admin.viewsUrl, {
      data: { name: survivor, starter: "marimo-studio/vanilla:default" },
      headers,
    });
    if (!created.ok()) {
      throw new Error(`Could not prepare Windows workspace cleanup: ${created.status()}`);
    }
  }
  for (const { name } of inventory.views) {
    if (name === survivor) {
      continue;
    }
    const target = new URL(admin.viewsUrl);
    target.pathname = `${target.pathname}/${encodeURIComponent(name)}`;
    const removed = await request.delete(target.href, { headers });
    if (!removed.ok()) {
      throw new Error(`Could not release view ${name}: ${removed.status()}`);
    }
  }
};

const closeNotebookSessions = async (page: Page, preparedAdmin?: SessionAdmin): Promise<void> => {
  const admin = preparedAdmin ?? (await sessionAdmin(page));
  const request = page.request;
  if (!page.isClosed()) {
    await page.close();
  }
  if (!admin) {
    return;
  }
  const headers = { "Marimo-Server-Token": admin.serverToken };
  const running = await request.post(`${admin.apiRoot}/running_notebooks`, {
    headers,
  });
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
  await expect
    .poll(async () => {
      const response = await request.post(`${admin.apiRoot}/running_notebooks`, { headers });
      if (!response.ok()) {
        throw new Error(`Could not inspect Marimo sessions: ${response.status()}`);
      }
      return sessionInventorySchema.parse(await response.json()).files.length;
    })
    .toBe(0);
  await releaseWindowsWorkspaceProjects(request, admin);
};

const cleanupBrowserWorkspace = async (
  page: Page,
  admin: SessionAdmin | undefined,
  managed: boolean,
  hosted: boolean,
): Promise<void> => {
  const cleanupErrors: unknown[] = [];
  try {
    if (managed) {
      await closeNotebookSessions(page, admin);
    } else if (!page.isClosed()) {
      await page.close();
    }
  } catch (error) {
    cleanupErrors.push(error);
  }
  try {
    if (hosted) {
      await restoreHostedWorkspace();
    } else {
      await restoreWorkspace();
    }
  } catch (error) {
    cleanupErrors.push(error);
  }
  if (cleanupErrors.length === 1) {
    throw cleanupErrors[0];
  }
  if (cleanupErrors.length > 1) {
    throw new AggregateError(cleanupErrors, "Browser teardown and workspace restore failed");
  }
};

export const retireWorkspacePage = async (
  page: Page,
  diagnostics: BrowserDiagnostics,
): Promise<void> => {
  const admin = await sessionAdmin(page);
  const retirement = diagnostics.expectPageRetirement(page);
  await page.close();
  retirement.recovered();
  await closeNotebookSessions(page, admin);
};

export const test = base.extend<{
  browserDiagnostics: BrowserDiagnosticsScope;
  collaborativeWorkspace: void;
  pyodideAssets: void;
}>({
  collaborativeWorkspace: async ({ browserName: _browserName }, use) => {
    await prepareCollaborativeWorkspace();
    await use();
  },
  pyodideAssets: [
    async ({ context }, use) => {
      await installPinnedPyodideAssets(context);
      await use();
    },
    { auto: true },
  ],
  browserDiagnostics: [
    async ({ context, page }, use, testInfo) => {
      const observed = observeBrowserContext(context);
      const { messages } = observed;

      await use(observed);

      const currentUrl = page.url();
      const hosted = currentUrl.startsWith(`${hostedOrigin}/`);
      const managed = hosted || currentUrl.startsWith(`${studioOrigin}/`);
      const retirement =
        process.platform === "win32" && !page.isClosed()
          ? observed.expectPageRetirement(page)
          : undefined;
      const admin = process.platform === "win32" && managed ? await sessionAdmin(page) : undefined;
      const studioDocument = !page.isClosed()
        ? await page.content().catch(() => undefined)
        : undefined;
      if (retirement !== undefined) {
        if (!page.isClosed()) {
          await page.close();
        }
        retirement.recovered();
      }
      await observed.close();

      try {
        if (messages.length > 0 || testInfo.status !== testInfo.expectedStatus) {
          await testInfo.attach("browser-diagnostics", {
            body: Buffer.from(messages.join("\n") || "No browser errors recorded."),
            contentType: "text/plain",
          });
          if (studioDocument !== undefined) {
            await testInfo.attach("studio-document", {
              body: Buffer.from(studioDocument),
              contentType: "text/html",
            });
          }
        }
        expect(messages, "unexpected browser diagnostics").toEqual([]);
      } finally {
        await cleanupBrowserWorkspace(page, admin, managed, hosted);
      }
    },
    { auto: true },
  ],
});

export { expect };
