import type { Page } from "@playwright/test";

import { viewProjectSchema } from "@marimo-studio/protocol/view-project";
import { viewListSchema } from "@marimo-studio/protocol/views";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  addWorkspaceView,
  buildWorkspaceView,
  captureProjectionRefresh,
  expect,
  expectSupersededRenewalConfig,
  exportWorkspaceView,
  labeledSlider,
  noDisplayStaticExportUrl,
  recoverRequestAbort,
  recoverProjectionRefresh,
  retireWorkspacePage,
  studioOrigin,
  test,
  waitForPreview,
  waitForViewPreview,
  workspaceNoDisplayNotebookPath,
  workspaceNoDisplayStaticExportPath,
  workspaceNotebookPath,
} from "./fixture.ts";

const noDisplayCases = [
  {
    heading: "Empty Html",
    starter: "marimo-studio/vanilla:default",
    view: "empty-html",
  },
  {
    heading: "Empty React",
    starter: "marimo-studio/react:default",
    view: "empty-react",
  },
  {
    heading: "No display results",
    starter: "marimo-studio/react:reveal",
    view: "empty-slides",
  },
  {
    heading: "Empty Svelte",
    starter: "marimo-studio/svelte:default",
    view: "empty-svelte",
  },
] as const;

const expectEmptyPreview = async (page: Page, candidate: (typeof noDisplayCases)[number]) => {
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

test("builds and renders every starter when no cell may display output", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(240_000);
  for (const candidate of noDisplayCases) {
    await addWorkspaceView(workspaceNoDisplayNotebookPath, candidate.view, candidate.starter);
    await buildWorkspaceView(candidate.view, workspaceNoDisplayNotebookPath);
  }
  await exportWorkspaceView(
    "empty-html",
    workspaceNoDisplayNotebookPath,
    workspaceNoDisplayStaticExportPath,
  );
  const supersededPresentations = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    method: "GET",
    path: /^\/(?:_marimo-studio\/presentation\/[^/]+\/)?(?:empty-html|empty-react|empty-slides|empty-svelte)\/$/,
    count: noDisplayCases.length,
    errorText: "net::ERR_ABORTED",
    required: false,
  });

  for (const [index, candidate] of noDisplayCases.entries()) {
    const candidatePage = index === 0 ? page : await page.context().newPage();
    try {
      await candidatePage.goto(`/studio/${candidate.view}/?file=no-display.py`);
      await expectEmptyPreview(candidatePage, candidate);
    } finally {
      if (candidatePage !== page && !candidatePage.isClosed()) {
        const retirement = browserDiagnostics.expectPageRetirement(candidatePage);
        await candidatePage.close();
        retirement.recovered();
      }
    }
  }

  const staticPage = await page.context().newPage();
  await staticPage.goto(noDisplayStaticExportUrl);
  await expect
    .poll(
      () =>
        staticPage
          .locator("html")
          .evaluate(async () => {
            if (!globalThis.marimoStudio) return false;
            await globalThis.marimoStudio.ready();
            return true;
          })
          .catch(() => false),
      { timeout: 65_000 },
    )
    .toBe(true);
  await expect(staticPage.getByRole("heading", { name: "Empty Html" })).toBeVisible();
  await staticPage.close();
  await retireWorkspacePage(page, browserDiagnostics);
  supersededPresentations.recovered();
});

test("keeps the active preview usable after a manifestless creation conflict", async ({
  browserDiagnostics,
  page,
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
    addWorkspaceView(workspaceNotebookPath, "blocked", "marimo-studio/vanilla:default"),
  ).rejects.toThrow(/exists without required view\.toml|directory changed/);
  expect(await readFile(sentinel, "utf8")).toBe("foreign-content");
  expect(await preview.locator("html").evaluate(() => globalThis.marimoStudio.identity())).toEqual(
    identity,
  );
  await labeledSlider(preview.locator('marimo-cell[name="controls"]'), /^Scale/).press("Home");
  await expect(preview.locator('strong[mo-value="metric"]')).toContainText("21");

  await rm(conflict, { recursive: true });
  await addWorkspaceView(workspaceNotebookPath, "blocked", "marimo-studio/vanilla:default");
  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "blocked", exact: true }).click();
  const recovered = await waitForPreview(page);
  await expect(recovered.getByRole("heading", { name: "Blocked" })).toBeVisible();
  await expect(
    labeledSlider(recovered.locator('marimo-cell[name="controls"]'), /^Scale/),
  ).toBeVisible();
  await recoverRequestAbort(abandonedHandoff);
  replacedWorkspaceStream.recovered();
  await retireWorkspacePage(page, browserDiagnostics);
  supersededPresentation.recovered();
});

test("publishes complete projects during concurrent starter creation", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(180_000);
  const candidates = [
    ["race-react-1", "marimo-studio/react:default"],
    ["race-svelte-1", "marimo-studio/svelte:default"],
    ["race-react-2", "marimo-studio/react:default"],
    ["race-svelte-2", "marimo-studio/svelte:default"],
  ] as const;
  const existingViews = new Set(["dashboard", "vanilla-local", "deno-seed"]);
  await addWorkspaceView(workspaceNotebookPath, "deno-seed", "marimo-studio/react:default");
  const supersededPresentations = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    method: "GET",
    path: /^\/(?:_marimo-studio\/presentation\/[^/]+\/)?dashboard\/$/,
    count: candidates.length,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  await page.goto("/?file=notebook.py");
  const dashboard = await waitForPreview(page);
  const initialRevision = await dashboard
    .locator("html")
    .evaluate(() => globalThis.marimoStudio.identity().revision);
  const dashboardRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  const supersededRenewal = expectSupersededRenewalConfig(browserDiagnostics, "dashboard");
  let complete = false;
  const creation = Promise.all(
    candidates.map(([view, starter]) => addWorkspaceView(workspaceNotebookPath, view, starter)),
  ).finally(() => {
    complete = true;
  });
  const observed = new Set<string>();

  const sampleCatalog = async () => {
    const response = await page.request.get("/_marimo-studio/views?file=notebook.py");
    expect(response.ok()).toBe(true);
    const inventory = viewListSchema.parse(await response.json());
    for (const { name } of inventory.views) {
      if (existingViews.has(name) || observed.has(name)) {
        continue;
      }
      const projectResponse = await page.request.get(
        `/_marimo-studio/views/${name}/project?file=notebook.py`,
      );
      expect(projectResponse.ok()).toBe(true);
      const project = viewProjectSchema.parse(await projectResponse.json());
      expect(project.view).toBe(name);
      observed.add(name);
    }
    return inventory;
  };

  while (!complete) {
    await sampleCatalog();
    await new Promise((resolveSample) => setTimeout(resolveSample, 10));
  }
  await creation;
  const finalInventory = await sampleCatalog();
  expect(new Set(finalInventory.views.map(({ name }) => name))).toEqual(
    new Set([...existingViews, ...candidates.map(([name]) => name)]),
  );
  expect(observed).toEqual(new Set(candidates.map(([name]) => name)));
  await page.getByLabel("Switch view").click();
  for (const [name] of candidates) {
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await page.keyboard.press("Escape");
  await expect
    .poll(() =>
      dashboard
        .locator("html")
        .evaluate(() => globalThis.marimoStudio.identity().revision)
        .catch(() => initialRevision),
    )
    .not.toBe(initialRevision);
  const refreshedDashboard = await waitForPreview(page);
  await labeledSlider(refreshedDashboard.locator('marimo-cell[name="controls"]'), /^Scale/).press(
    "End",
  );
  await expect(refreshedDashboard.locator('strong[mo-value="metric"]')).toContainText("63");
  await recoverProjectionRefresh(dashboardRefresh, page);
  supersededRenewal.recovered();
  await retireWorkspacePage(page, browserDiagnostics);
  supersededPresentations.recovered();
});
