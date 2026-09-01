import type { ElementHandle, Page } from "@playwright/test";

import { rm } from "node:fs/promises";
import { resolve } from "node:path";

import { workspaceDirectory } from "../scripts/paths.mjs";
import { selectAllShortcut } from "./authoring-test-support.ts";
import {
  addWorkspaceView,
  captureProjectionRefresh,
  editorFrame,
  expect,
  expectEditorModelReplayRecovery,
  readWorkspaceFile,
  recoverRequestAbort,
  retireWorkspacePage,
  studioEntryUrl,
  studioOrigin,
  recoverProjectionRefresh,
  test,
  waitForPreview,
  waitForViewPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

interface ViewTiming {
  authoredMs: number;
  boot: number;
  frame: ElementHandle<HTMLElement | SVGElement>;
  liveMs: number;
}

const generatedViews = ["report", "gallery"] as const;

const runtimeIdentity = async (page: Page) =>
  await (await waitForPreview(page)).locator("html").evaluate(() => marimoStudio.identity());

const replaceMetricCell = async (page: Page, source: string) => {
  const cell = editorFrame(page)
    .locator(".cm-content")
    .filter({ hasText: /metric = scale\.value \* 21/ })
    .first();
  const editor = await cell.elementHandle();
  if (!editor) {
    throw new Error("The metric cell editor is unavailable");
  }
  await editor.click();
  await editor.press(selectAllShortcut);
  await page.keyboard.insertText(source);
  await editorFrame(page)
    .locator('[data-cell-name="metric"]')
    .getByTestId("run-button")
    .first()
    .click();
};

test.afterAll(async () => {
  await Promise.all(
    generatedViews.map((view) =>
      rm(resolve(workspaceDirectory, "__marimo__/studio/notebook", view), {
        force: true,
        recursive: true,
      }),
    ),
  );
});

const selectView = async (page: Page, view: string, heading: string): Promise<ViewTiming> => {
  const started = performance.now();
  const committed = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.status() === 204 &&
      response.request().method() === "POST" &&
      /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/.test(url.pathname)
    );
  });
  await page.getByLabel("Switch view").click();
  const accessibleName = view === "dashboard" ? "dashboard, default" : view;
  await page.getByRole("button", { name: accessibleName, exact: true }).click();
  await committed;
  const preview = await waitForViewPreview(page, view);
  await expect(preview.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  const authoredMs = performance.now() - started;
  const liveMs = performance.now() - started;
  const boot = await preview.locator("html").evaluate(() => performance.timeOrigin);
  const frame = await page.locator('iframe[data-preview-runtime-frame="server"]').elementHandle();
  if (!boot || !frame) {
    throw new Error(`The ${view} preview did not expose its document identity`);
  }
  return { authoredMs, boot, frame, liveMs };
};

test("reuses isolated named-view documents after their cold load", async ({
  browserDiagnostics,
  page,
}, testInfo) => {
  for (const view of generatedViews) {
    await addWorkspaceView(workspaceNotebookPath, view);
  }
  await page.goto(studioEntryUrl);
  const dashboardPreview = await waitForPreview(page);
  const dashboardBoot = await dashboardPreview
    .locator("html")
    .evaluate(() => performance.timeOrigin);
  const dashboardFrame = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  if (!dashboardBoot || !dashboardFrame) {
    throw new Error("The dashboard preview did not expose its document identity");
  }

  const streamChanges = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    5,
  );
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 5,
    required: false,
    status: 204,
  });
  const coldReport = await selectView(page, "report", "Report");
  const coldGallery = await selectView(page, "gallery", "Gallery");
  const warmDashboard = await selectView(page, "dashboard", "Studio browser fixture");
  const warmReport = await selectView(page, "report", "Report");
  await selectView(page, "dashboard", "Studio browser fixture");

  expect(new Set([dashboardBoot, coldReport.boot, coldGallery.boot]).size).toBe(3);
  expect(warmDashboard.boot).toBe(dashboardBoot);
  expect(warmReport.boot).toBe(coldReport.boot);
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [dashboardFrame, warmDashboard.frame],
    ),
  ).toBe(true);
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [coldReport.frame, warmReport.frame],
    ),
  ).toBe(true);
  await recoverRequestAbort(abandonedHandoffs);
  streamChanges.recovered();

  await testInfo.attach("named-view-cache-timings", {
    body: Buffer.from(
      JSON.stringify(
        {
          coldReport: {
            authoredMs: coldReport.authoredMs,
            liveMs: coldReport.liveMs,
          },
          coldGallery: {
            authoredMs: coldGallery.authoredMs,
            liveMs: coldGallery.liveMs,
          },
          warmDashboard: {
            authoredMs: warmDashboard.authoredMs,
            liveMs: warmDashboard.liveMs,
          },
          warmReport: {
            authoredMs: warmReport.authoredMs,
            liveMs: warmReport.liveMs,
          },
        },
        null,
        2,
      ),
    ),
    contentType: "application/json",
  });
  await retireWorkspacePage(page, browserDiagnostics);
});

test("reloads a cached sibling after notebook state changes", async ({
  browserDiagnostics,
  page,
}) => {
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await addWorkspaceView(workspaceNotebookPath, "report");
  const reportPath = resolve(workspaceDirectory, "__marimo__/studio/notebook/report/index.html");
  const reportSource = await readWorkspaceFile(reportPath);
  const resultsSection = '<section class="view-results" aria-label="Notebook results">';
  const projectedReport = reportSource.replace(
    resultsSection,
    `${resultsSection}<strong mo-value="metric"></strong>`,
  );
  if (projectedReport === reportSource) {
    throw new Error("Could not find the report notebook-results section");
  }
  await writeWorkspaceFile(reportPath, projectedReport);
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await editorModelRecovery.recovered(page);
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 3,
    required: false,
    status: 204,
  });
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    4,
  );
  const cold = await selectView(page, "report", "Report");
  const report = await waitForPreview(page);
  await expect(report.locator('[mo-value="metric"]')).toHaveText("42");
  const coldIdentity = await runtimeIdentity(page);

  await selectView(page, "dashboard", "Studio browser fixture");
  const dashboardIdentity = await runtimeIdentity(page);
  const dashboardRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await replaceMetricCell(
    page,
    'metric = scale.value * 22\nresponsive_value = "responsive" * 80\nmetric',
  );
  await expect((await waitForPreview(page)).locator('[mo-value="metric"]')).toHaveText("44");
  await expect
    .poll(async () => (await runtimeIdentity(page)).projectionRevision)
    .not.toBe(dashboardIdentity.projectionRevision);
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain("scale.value * 22");
  await expect.poll(() => cold.frame.getAttribute("src")).toBe("about:blank");
  await recoverProjectionRefresh(dashboardRefresh, page);

  const reloaded = await selectView(page, "report", "Report");
  const reloadedReport = await waitForPreview(page);
  expect(await reloadedReport.locator('[mo-value="metric"]').textContent()).toBe("44");
  const reloadedIdentity = await runtimeIdentity(page);
  expect(
    await page.evaluate(([before, after]) => before === after, [cold.frame, reloaded.frame]),
  ).toBe(true);
  expect(reloaded.boot).not.toBe(cold.boot);
  expect(reloadedIdentity.revision).not.toBe(coldIdentity.revision);
  expect(reloadedIdentity.projectionRevision).not.toBe(coldIdentity.projectionRevision);
  await recoverRequestAbort(abandonedHandoffs);
  replacedWorkspaceStreams.recovered();
  await retireWorkspacePage(page, browserDiagnostics);
});
