import { parseMountConfig, type MountConfig } from "@marimo-studio/protocol/runtime-config";
import { viewProjectSchema } from "@marimo-studio/protocol/view-project";
import { deletedViewSchema, viewListSchema } from "@marimo-studio/protocol/views";
import {
  expect,
  type APIRequestContext,
  type FrameLocator,
  type Locator,
  type Page,
} from "@playwright/test";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";

import { prepareCollaborativeWorkspace } from "../scripts/collaborative-workspace.ts";
import { withExportRepository } from "../scripts/export-repository.ts";
import { copyFixtureProviderPackage } from "../scripts/fixture-provider-package.ts";
import { MainWorkspace } from "../scripts/main-workspace.ts";
import { e2eNetwork } from "../scripts/network.ts";
import {
  collaborativeWorkspaceDirectory,
  configDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  notebookPath,
  noDisplayNotebookPath,
  noDisplayStaticExportDirectory,
  proxiedFixtureDirectory,
  proxiedNotebookPath,
  proxiedWorkspaceDirectory,
  workspaceDirectory,
} from "../scripts/paths.ts";
import { captureRetiringProjectionReads } from "./authoring-test-support.ts";
import {
  observeBrowserContext,
  type BrowserDiagnostics,
  type BrowserDiagnosticsScope,
  type BrowserResponseRecovery,
  type ProjectionRefreshCapture,
  type RequestAbortCapture,
  type ResponseTransitionCapture,
  type WorkspaceEventStreamCapture,
} from "./browser-diagnostics.ts";
import { test as base } from "./network-fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";
import { StudioCli } from "./studio-cli.ts";

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

const dashboardDirectory = resolve(workspaceDirectory, "__marimo__/studio/notebook/dashboard");
const collaborativeDashboardDirectory = resolve(
  collaborativeWorkspaceDirectory,
  "__marimo__/studio/notebook/dashboard",
);
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
export const studioOrigin = () => e2eNetwork.main.studio.origin;
export const hostedOrigin = () => e2eNetwork.main.hosted.origin;
export const studioEntryUrl = "/?file=notebook.py";
export const collaborativeStudioEntryUrl = () =>
  `${e2eNetwork.main.collaboration.origin}/?file=notebook.py`;
export const staticExportUrl = () => `${e2eNetwork.main.exported.origin}/src/index.html`;
export const noDisplayStaticExportUrl = () =>
  `${e2eNetwork.main.exported.origin}/no-display/index.html`;

const sessionAdminBootstrapSchema = z.object({
  serverToken: z.string(),
  urls: z.object({ views: z.string() }),
});
export const sessionInventorySchema = z.object({
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
  await copyFixtureProviderPackage(workspaceDirectory);
  await removeTree(resolve(workspaceDirectory, "__marimo__/session"));
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/notebook"));
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/no-display"));
  await copyFixtureFile("notebook.py");
  await copyFixtureFile("no-display.py");
  await removeTree(noDisplayStaticExportDirectory);
  await copyFixtureFile("plain.py");
  await rm(resolve(workspaceDirectory, "first-save.py"), { force: true });
  await rm(resolve(workspaceDirectory, "lens-onboarding.py"), { force: true });
  await removeTree(resolve(workspaceDirectory, "__marimo__/studio/lens-onboarding"));
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/view.toml");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/index.html");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/app.css");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/scripts/app.js");
  await copyFixtureFile("__marimo__/studio/notebook/dashboard/src/scripts/message.js");
  await copyFixtureFile("__marimo__/studio/notebook/vanilla-local/view.toml");
  await copyFixtureFile("__marimo__/studio/notebook/vanilla-local/index.html");
  await copyFixtureFile("__marimo__/studio/notebook/vanilla-local/styles/app.css");
  await copyFixtureFile("__marimo__/studio/notebook/vanilla-local/scripts/app.js");
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

export const restoreProxiedWorkspace = async () => {
  await removeTree(resolve(proxiedWorkspaceDirectory, "__marimo__"));
  await cp(resolve(proxiedFixtureDirectory, "notebook.py"), proxiedNotebookPath, { force: true });
};

export const hostedWorkspaceNotebookPath = hostedNotebookPath;
export const proxiedFixturePath = (name: string) => resolve(proxiedFixtureDirectory, name);
export const proxiedWorkspacePath = (...parts: string[]) =>
  resolve(proxiedWorkspaceDirectory, ...parts);
// Public roots of the proxied servers, each beneath its random path prefix.
export const proxiedUrl = () => `${e2eNetwork.main.proxied.publicUrl}/`;
export const proxiedRunUrl = () => `${e2eNetwork.main.proxiedRun.publicUrl}/`;
export const proxiedDirectoryUrl = () => `${e2eNetwork.main.proxiedDirectory.publicUrl}/`;

/** Read a presentation document's mount record as its runtime parses it. */
export const presentationMount = async (root: Locator): Promise<MountConfig> => {
  const { config, base } = await root.evaluate(() => ({
    config: globalThis.__MARIMO_MOUNT_CONFIG__,
    base: document.baseURI,
  }));
  return parseMountConfig(config, base);
};

export const readWorkspaceFile = (path: string) => readFile(path, "utf8");
export const writeWorkspaceFile = (path: string, content: string) => writeFile(path, content);

declare global {
  var __e2eRuntimeMarker: string | undefined;
}

export const editorFrame = (page: Page): FrameLocator =>
  page.frameLocator('iframe[title="Marimo editor"]');

export const labeledSlider = (root: FrameLocator | Locator, label: RegExp | string): Locator =>
  root.locator("marimo-slider").filter({ hasText: label }).getByRole("slider");

export const editorSlider = (page: Page, label: RegExp | string = /^Scale/) =>
  labeledSlider(editorFrame(page), label);

export const PREVIEW_TIMEOUT = process.platform === "win32" ? 120_000 : 65_000;

export const expectEditorModelReplayRecovery = (diagnostics: BrowserDiagnostics, count = 1) => {
  const recovery: BrowserResponseRecovery = diagnostics.expectConsole({
    type: "error",
    text: /^Error: Model not found for key: [a-f\d]{32}\n\s+at http:\/\/127\.0\.0\.1:\d+\/_marimo-studio\/editor\/assets\/state-[^/\s]+\.js:\d+:\d+$/,
    count,
    required: false,
  });
  return {
    ready: async (page: Page): Promise<void> => {
      await expect(editorFrame(page).getByRole("button", { name: "Widget count: 7" })).toBeVisible({
        timeout: PREVIEW_TIMEOUT,
      });
    },
    recovered: recovery.recovered,
  };
};

export const presentationFrame = (page: Page): FrameLocator =>
  page.frameLocator("iframe#marimo-studio-presentation");

export const previewFrame = (page: Page, runtime = "server"): FrameLocator =>
  page.frameLocator(`iframe[data-preview-runtime-frame="${runtime}"]`);

export const expectPreviewInteractive = async (page: Page, runtime: "server" | "wasm") => {
  const frame = page.locator(`iframe[data-preview-runtime-frame="${runtime}"]`);
  await expect(frame).not.toHaveAttribute("inert");
  await expect(frame).not.toHaveAttribute("aria-busy");
};

export const WASM_PREVIEW_TIMEOUT = 125_000;

const waitForPreviewFrame = async (page: Page, selector: string, timeout = PREVIEW_TIMEOUT) => {
  const deadline = Date.now() + timeout;
  const remaining = () => Math.max(1, deadline - Date.now());
  const frame = page.locator(selector);
  await expect(frame).toBeAttached({ timeout: remaining() });
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
      { timeout: remaining() },
    )
    .toBe(true);
  await expect(frame).not.toHaveAttribute("inert", { timeout: remaining() });
  await expect(frame).not.toHaveAttribute("aria-busy", { timeout: remaining() });
  return preview;
};

export const waitForPreview = async (page: Page, runtime = "server", timeout = PREVIEW_TIMEOUT) =>
  waitForPreviewFrame(page, `iframe[data-preview-runtime-frame="${runtime}"]`, timeout);

export const waitForViewPreview = async (
  page: Page,
  view: string,
  runtime = "server",
  timeout = PREVIEW_TIMEOUT,
) =>
  waitForPreviewFrame(
    page,
    `iframe[data-preview-view-frame="${view}"][data-preview-runtime-frame="${runtime}"]`,
    timeout,
  );

interface ProjectionRefreshScope {
  readonly capture: ProjectionRefreshCapture;
  readonly initialRevision: string;
  readonly staleReads: ReturnType<typeof captureRetiringProjectionReads>;
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
  const identity = await preview.locator("html").evaluate(() => globalThis.marimoStudio.identity());
  const initialRevision = identity.projectionRevision;
  return {
    capture: diagnostics.expectProjectionRefresh(frame, initialRevision),
    initialRevision,
    staleReads: captureRetiringProjectionReads(frame, identity.revision, diagnostics),
  };
};

// A rebuild swaps the server preview to the next revision. Until the swap lands,
// the retiring revision's runtime reads can answer 409.
export const captureRetiringPreviewReads = async (
  page: Page,
  diagnostics: BrowserDiagnostics,
): Promise<ReturnType<typeof captureRetiringProjectionReads>> => {
  const frameElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const frame = await frameElement?.contentFrame().finally(() => frameElement.dispose());
  const revision = await previewFrame(page)
    .locator("html")
    .getAttribute("data-marimo-studio-revision");
  if (frame === null || frame === undefined || revision === null) {
    throw new Error("The server preview frame is unavailable.");
  }
  return captureRetiringProjectionReads(frame, revision, diagnostics);
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
  scope.staleReads.seal();
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
  scope.staleReads.recovered();
};

export const recoverRequestAbort = async (capture: RequestAbortCapture): Promise<void> => {
  capture.seal();
  await expect.poll(() => capture.ready(), { timeout: 10_000 }).toBe(true);
  if (!capture.recovered()) {
    throw new Error("The request abort changed while recovery was committing.");
  }
};

// A rebuild swaps an open preview to the next revision. The swap retires the
// previous revision's runtime reads and its live event stream. Recover before
// closing the preview, which would end that stream whether or not the swap did.
export const expectPreviewRevisionSwap = async (
  diagnostics: BrowserDiagnostics,
  preview: Page,
  root: string,
  view: string,
): Promise<() => Promise<void>> => {
  const { origin, pathname } = new URL(root);
  const reads = `^${RegExp.escape(pathname)}_marimo-studio/presentation/[^/]+/_marimo-studio/views/${view}/`;
  const revision = await preview.locator("html").getAttribute("data-marimo-studio-revision");
  expect(revision).toBeTruthy();
  // A retired read can lose its response body, so stale reads are matched by
  // the revision they carry.
  const staleReads = captureRetiringProjectionReads(preview.mainFrame(), revision!, diagnostics);
  const staleManifest = diagnostics.expectResponse({
    status: 409,
    path: new RegExp(`${reads}zero-python/current$`),
    error: "stale-projection-binding",
    required: false,
  });
  const retiredReads = diagnostics.expectRequestFailure({
    origin,
    method: "POST",
    path: new RegExp(`${reads}(?:values|outputs)$`),
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  const retiredStream = diagnostics.expectActiveRequestAbort({
    origin,
    method: "GET",
    path: new RegExp(`${reads}dev/events$`),
    status: 200,
  });
  return async () => {
    staleReads.recovered();
    staleManifest.recovered();
    retiredReads.recovered();
    await recoverRequestAbort(retiredStream);
  };
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
  const bootstrapElement = page.locator("#marimo-studio-workspace");
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
  const projectResponse = await page.request.get(
    `/_marimo-studio/views/${encodeURIComponent(view)}/project?file=${encodeURIComponent(file)}`,
  );
  const project = viewProjectSchema.parse(await projectResponse.json());
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
      "Marimo-Studio-Catalog-Generation": project.catalog_generation,
      "Marimo-Server-Token": await studioServerToken(page),
      "Marimo-Studio-View-Generation": project.view_generation,
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
  const inventoryUrl = `/_marimo-studio/views?file=${encodeURIComponent(file)}`;
  const inventoryResponse = await page.request.get(inventoryUrl);
  const inventory = viewListSchema.parse(await inventoryResponse.json());
  const target = inventory.views.find((item) => item.name === view);
  if (!target) {
    throw new Error(`Could not find ${view} in the current Studio inventory`);
  }
  const response = await page.request.delete(
    `/_marimo-studio/views/${encodeURIComponent(view)}?file=${encodeURIComponent(file)}`,
    {
      data: {
        catalog_generation: inventory.generation,
        name: view,
        view_generation: target.generation,
      },
      headers: { "Marimo-Server-Token": await studioServerToken(page) },
    },
  );
  if (!response.ok()) {
    throw new Error(`Could not remove ${view} (${response.status()}): ${await response.text()}`);
  }
};

const releaseWorkspaceProjects = async (
  request: APIRequestContext,
  admin: SessionAdmin,
): Promise<void> => {
  const headers = { "Marimo-Server-Token": admin.serverToken };
  const response = await request.get(admin.viewsUrl);
  if (!response.ok()) {
    throw new Error(`Could not inspect Studio views: ${response.status()}`);
  }
  let inventory = viewListSchema.parse(await response.json());
  const survivor = "fixture-cleanup";
  if (!inventory.views.some(({ name }) => name === survivor)) {
    const created = await request.post(admin.viewsUrl, {
      data: {
        catalog_generation: inventory.generation,
        name: survivor,
        starter: "marimo-studio/vanilla:default",
      },
      headers,
    });
    if (!created.ok()) {
      throw new Error(`Could not prepare workspace cleanup: ${created.status()}`);
    }
    const refreshed = await request.get(admin.viewsUrl);
    if (!refreshed.ok()) {
      throw new Error(`Could not refresh Studio views: ${refreshed.status()}`);
    }
    inventory = viewListSchema.parse(await refreshed.json());
  }
  for (const { name } of inventory.views) {
    if (name === survivor) {
      continue;
    }
    const target = new URL(admin.viewsUrl);
    target.pathname = `${target.pathname}/${encodeURIComponent(name)}`;
    const owner = inventory.views.find((view) => view.name === name);
    if (!owner) {
      continue;
    }
    const removed = await request.delete(target.href, {
      data: {
        catalog_generation: inventory.generation,
        name,
        view_generation: owner.generation,
      },
      headers,
    });
    if (!removed.ok()) {
      throw new Error(`Could not release view ${name}: ${removed.status()}`);
    }
    inventory = deletedViewSchema.parse(await removed.json());
  }
};

const closeNotebookSessions = async (
  page: Page,
  preparedAdmin?: SessionAdmin,
  releaseProjects = true,
): Promise<void> => {
  const admin = preparedAdmin ?? (await sessionAdmin(page));
  const request = page.request;
  await Promise.all(
    page
      .context()
      .pages()
      .map((ownedPage) => ownedPage.close()),
  );
  if (!admin) {
    return;
  }
  const headers = { "Marimo-Server-Token": admin.serverToken };
  // A kernel connection that a closing page started can reach the server after
  // a shutdown, and marimo starts a fresh kernel for its session id. Each pass
  // closes whatever is still running.
  await expect
    .poll(async () => {
      const running = await request.post(`${admin.apiRoot}/running_notebooks`, { headers });
      if (!running.ok()) {
        throw new Error(`Could not list Marimo sessions: ${running.status()}`);
      }
      const { files } = sessionInventorySchema.parse(await running.json());
      for (const file of files) {
        const closed = await request.post(`${admin.apiRoot}/shutdown_session`, {
          data: { sessionId: file.sessionId },
          headers,
        });
        if (!closed.ok()) {
          throw new Error(`Could not close Marimo session: ${closed.status()}`);
        }
      }
      return files.length;
    })
    .toBe(0);
  if (releaseProjects) {
    await releaseWorkspaceProjects(request, admin);
  }
};

type BrowserWorkspace = "main" | "hosted" | "proxied" | "proxiedRun" | "proxiedDirectory";

const browserWorkspace = (url: string): BrowserWorkspace => {
  if (url.startsWith(`${hostedOrigin()}/`)) return "hosted";
  if (url.startsWith(proxiedUrl())) return "proxied";
  if (url.startsWith(proxiedRunUrl())) return "proxiedRun";
  if (url.startsWith(proxiedDirectoryUrl())) return "proxiedDirectory";
  return "main";
};

const cleanupBrowserWorkspace = async (
  page: Page,
  admin: SessionAdmin | undefined,
  managed: boolean,
  workspace: BrowserWorkspace,
): Promise<void> => {
  // The proxied run and directory servers prepare their views once per worker.
  // Cleanup closes notebook sessions and keeps those views.
  if (workspace === "proxiedDirectory") {
    await closeNotebookSessions(page, admin, false);
    return;
  }
  if (managed) {
    await closeNotebookSessions(page, admin);
  } else if (!page.isClosed()) {
    await page.close();
  }
  if (workspace === "hosted") {
    await restoreHostedWorkspace();
  } else if (workspace === "proxied") {
    await restoreProxiedWorkspace();
  } else if (workspace === "main") {
    await restoreWorkspace();
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

export const test = base.extend<
  {
    browserDiagnostics: BrowserDiagnosticsScope;
    collaborativeWorkspace: void;
    pyodideAssets: void;
    studioCli: StudioCli;
  },
  {
    services: readonly (
      | "studio"
      | "hosted"
      | "static"
      | "proxied"
      | "proxiedRun"
      | "proxiedDirectory"
    )[];
    mainWorkspace: MainWorkspace;
  }
>({
  services: [["studio"], { option: true, scope: "worker" }],
  mainWorkspace: [
    async ({ services, network: _network }, use) =>
      withExportRepository(resolve(configDirectory, "export-repository"), async () => {
        const workspace = new MainWorkspace();
        const failures: unknown[] = [];
        try {
          await workspace.prepare();
          await workspace.start(services);
          await use(workspace);
        } catch (error) {
          failures.push(error);
        }
        try {
          await workspace.close();
        } catch (error) {
          failures.push(error);
        }
        if (failures.length === 1) throw failures[0];
        if (failures.length > 1) {
          throw new AggregateError(failures, "Browser workspace setup and teardown failed");
        }
      }),
    { scope: "worker", auto: true, timeout: 180_000 },
  ],
  baseURL: async ({ mainWorkspace: _mainWorkspace }, use) => {
    await use(studioOrigin());
  },
  studioCli: async ({ browserName: _browserName }, use) => {
    const studioCli = new StudioCli();
    try {
      await use(studioCli);
    } finally {
      await studioCli.close();
    }
  },
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
      // Prefix-mounted endpoints record every request outside their prefix.
      const prefixed = [
        e2eNetwork.main.proxied,
        e2eNetwork.main.proxiedRun,
        e2eNetwork.main.proxiedDirectory,
      ];
      const escapes = prefixed.map((endpoint) => endpoint.escapedRequests().length);
      const escapedSince = (counts: number[]) =>
        prefixed.flatMap((endpoint, index) =>
          endpoint
            .escapedRequests()
            .slice(counts[index])
            .map((request) => `request escaped ${endpoint.publicUrl}/: ${request}`),
        );

      await use(observed);

      messages.push(...escapedSince(escapes));
      const settled = prefixed.map((endpoint) => endpoint.escapedRequests().length);
      const currentUrl = page.url();
      const workspace = browserWorkspace(currentUrl);
      const managed =
        workspace === "hosted" ||
        workspace === "proxied" ||
        workspace === "proxiedDirectory" ||
        currentUrl.startsWith(`${studioOrigin()}/`);
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
        await cleanupBrowserWorkspace(page, admin, managed, workspace);
      }
      // Pages that close during cleanup still belong to this test.
      expect(escapedSince(settled), "requests escaped a proxy prefix during cleanup").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export const selectWorkspaceMode = async (page: Page, mode: string): Promise<void> => {
  const options = page.getByLabel("Workspace options", { exact: true });
  if (!(await options.locator("..").evaluate((menu) => menu.hasAttribute("open")))) {
    await options.click();
  }
  const labels = new Map([
    ["Notebook", "Focus Notebook"],
    ["Develop", "Split Notebook and View"],
    ["Preview", "Focus View"],
    ["Source", "Focus Source"],
  ]);
  await page.getByRole("button", { name: labels.get(mode) ?? mode, exact: true }).click();
};
