import type { Page } from "@playwright/test";

import { viewProjectSchema } from "@marimo-studio/protocol/view-project";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  captureProjectionRefresh,
  expect,
  labeledSlider,
  noDisplayStaticExportUrl,
  recoverRequestAbort,
  recoverResponseTransition,
  recoverProjectionRefresh,
  recoverWorkspaceEventStream,
  retireWorkspacePage,
  studioOrigin,
  test,
  waitForPreview,
  waitForViewPreview,
  workspaceNoDisplayNotebookPath,
  workspaceNoDisplayStaticExportPath,
  workspaceNotebookPath,
} from "./fixture.ts";

const noDisplayView = {
  heading: "Empty Html",
  starter: "marimo-studio/vanilla:default",
  view: "empty-html",
} as const;

test.use({ services: ["studio", "static"] });

const expectEmptyPreview = async (page: Page, candidate: typeof noDisplayView) => {
  const preview = await waitForViewPreview(page, candidate.view);
  await expect(preview.getByRole("heading", { name: candidate.heading })).toBeVisible({
    timeout: 65_000,
  });
  await expect
    .poll(() =>
      preview.locator("html").evaluate(() => ({
        diagnostics: globalThis.marimoStudio.diagnostics().length,
        projections: globalThis.marimoStudio.projections().length,
      })),
    )
    .toEqual({ diagnostics: 0, projections: 0 });
};

test("builds, renders, and exports a view when no cell may display output", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await studioCli.addWorkspaceView(
    workspaceNoDisplayNotebookPath,
    noDisplayView.view,
    noDisplayView.starter,
  );
  await studioCli.buildWorkspaceView(noDisplayView.view, workspaceNoDisplayNotebookPath);
  await studioCli.exportWorkspaceView(
    noDisplayView.view,
    workspaceNoDisplayNotebookPath,
    workspaceNoDisplayStaticExportPath,
  );

  await page.goto(`/studio/${noDisplayView.view}/?file=no-display.py`);
  await expectEmptyPreview(page, noDisplayView);

  const staticPage = await page.context().newPage();
  await staticPage.goto(noDisplayStaticExportUrl);
  await expect(staticPage.getByRole("heading", { name: "Empty Html" })).toBeVisible({
    timeout: 65_000,
  });
  await staticPage.close();
  await retireWorkspacePage(page, browserDiagnostics);
});

test("keeps the active preview usable after a manifestless creation conflict", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const supersededPresentation = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    method: "GET",
    path: /^\/(?:_marimo-studio\/presentation\/[^/]+\/)?(?:dashboard|blocked)\/$/,
    count: 1,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  await page.goto("/?file=notebook.py");
  const preview = await waitForPreview(page);
  const abandonedHandoff = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 1,
    status: 204,
  });
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    1,
  );
  const identity = await preview.locator("html").evaluate(() => globalThis.marimoStudio.identity());
  const conflict = resolve(workspaceNotebookPath, "../__marimo__/studio/notebook/blocked");
  const sentinel = resolve(conflict, "public/sentinel.js");
  await mkdir(resolve(sentinel, ".."), { recursive: true });
  await writeFile(sentinel, "foreign-content", "utf8");

  await expect(
    studioCli.addWorkspaceView(workspaceNotebookPath, "blocked", "marimo-studio/vanilla:default"),
  ).rejects.toThrow(/exists without required view\.toml|directory changed/);
  expect(await readFile(sentinel, "utf8")).toBe("foreign-content");
  expect(await preview.locator("html").evaluate(() => globalThis.marimoStudio.identity())).toEqual(
    identity,
  );
  await labeledSlider(preview.locator('marimo-cell[name="controls"]'), /^Scale/).press("Home");
  await expect(preview.locator('strong[mo-value="metric"]')).toContainText("21");

  await rm(conflict, { recursive: true });
  await studioCli.addWorkspaceView(
    workspaceNotebookPath,
    "blocked",
    "marimo-studio/vanilla:default",
  );
  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "blocked", exact: true }).click();
  const recovered = await waitForPreview(page);
  await expect(recovered.getByRole("heading", { name: "Blocked" })).toBeVisible();
  await expect(
    labeledSlider(recovered.locator('marimo-cell[name="controls"]'), /^Scale/),
  ).toBeVisible();
  await recoverRequestAbort(abandonedHandoff);
  await recoverWorkspaceEventStream(replacedWorkspaceStream);
  await retireWorkspacePage(page, browserDiagnostics);
  supersededPresentation.recovered();
});

test("creates distinct provider projects concurrently and refreshes the active view", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  test.setTimeout(180_000);
  const candidates = [
    ["race-react", "marimo-studio/react:default"],
    ["race-svelte", "marimo-studio/svelte:default"],
  ] as const;
  await studioCli.addWorkspaceView(
    workspaceNotebookPath,
    "deno-seed",
    "marimo-studio/react:default",
  );
  await page.goto("/?file=notebook.py");
  const dashboard = await waitForPreview(page);
  const dashboardRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  const documentPath = await dashboard.locator("html").evaluate(() => location.pathname);
  const documentRefresh = browserDiagnostics.expectResponseTransition(page, {
    origin: studioOrigin,
    method: "GET",
    path: new RegExp(`^${documentPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
    failureStatus: 409,
    failureError: "workspace-generation-conflict",
    successStatus: 200,
    count: candidates.length,
  });
  await Promise.all(
    candidates.map(([view, starter]) =>
      studioCli.addWorkspaceView(workspaceNotebookPath, view, starter),
    ),
  );
  documentRefresh.seal();
  await page.getByLabel("Switch view").click();
  for (const [name] of candidates) {
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible({
      timeout: 65_000,
    });
    const projectResponse = await page.request.get(
      `/_marimo-studio/views/${name}/project?file=notebook.py`,
    );
    expect(projectResponse.ok()).toBe(true);
    expect(viewProjectSchema.parse(await projectResponse.json()).view).toBe(name);
  }
  await page.keyboard.press("Escape");
  const refreshedDashboard = await waitForPreview(page);
  await labeledSlider(refreshedDashboard.locator('marimo-cell[name="controls"]'), /^Scale/).press(
    "End",
  );
  await expect(refreshedDashboard.locator('strong[mo-value="metric"]')).toContainText("63");
  await recoverProjectionRefresh(dashboardRefresh, page);
  await recoverResponseTransition(documentRefresh);
  await retireWorkspacePage(page, browserDiagnostics);
});
