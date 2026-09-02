import type { Page } from "@playwright/test";

import { rm } from "node:fs/promises";
import { resolve } from "node:path";

import { workspaceDirectory } from "../scripts/paths.mjs";
import { selectAllShortcut } from "./authoring-test-support.ts";
import {
  captureProjectionRefresh,
  editorFrame,
  expect,
  expectEditorModelReplayRecovery,
  readWorkspaceFile,
  recoverRequestAbort,
  recoverResponseTransition,
  recoverWorkspaceEventStream,
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

const generatedViews = ["report", "gallery"] as const;

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

const selectView = async (page: Page, view: string, heading: string) => {
  const streamReady = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.status() === 200 &&
      response.request().method() === "GET" &&
      url.origin === studioOrigin &&
      url.pathname === "/_marimo-studio/dev/events" &&
      url.searchParams.get("marimo_studio_view") === view
    );
  });
  await page.getByLabel("Switch view").click();
  const accessibleName = view === "dashboard" ? "dashboard, default" : view;
  await page.getByRole("button", { name: accessibleName, exact: true }).click();
  const preview = await waitForViewPreview(page, view);
  await expect(preview.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  await streamReady;
  return preview;
};

test("reuses isolated named-view documents after their cold load", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  for (const view of generatedViews) {
    await studioCli.addWorkspaceView(workspaceNotebookPath, view);
    const path = resolve(workspaceDirectory, `__marimo__/studio/notebook/${view}/index.html`);
    const source = await readWorkspaceFile(path);
    const withDraft = source.replace(
      "</main>",
      `<label>${view} draft <input aria-label="${view} draft"></label></main>`,
    );
    if (withDraft === source) {
      throw new Error(`The ${view} fixture has no main element`);
    }
    await writeWorkspaceFile(path, withDraft);
  }
  await page.goto(studioEntryUrl);
  await waitForPreview(page);

  const streamChanges = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    4,
  );
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 4,
    required: false,
    status: 204,
  });
  const report = await selectView(page, "report", "Report");
  await report.getByRole("textbox", { name: "report draft" }).fill("report notes");
  const gallery = await selectView(page, "gallery", "Gallery");
  await gallery.getByRole("textbox", { name: "gallery draft" }).fill("gallery notes");
  await expect(
    (await selectView(page, "report", "Report")).getByRole("textbox", {
      name: "report draft",
    }),
  ).toHaveValue("report notes");
  await expect(
    (await selectView(page, "gallery", "Gallery")).getByRole("textbox", {
      name: "gallery draft",
    }),
  ).toHaveValue("gallery notes");
  await recoverRequestAbort(abandonedHandoffs);
  await recoverWorkspaceEventStream(streamChanges);

  await retireWorkspacePage(page, browserDiagnostics);
});

test("reloads a cached sibling after notebook state changes", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  test.setTimeout(180_000);
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report");
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
  await selectView(page, "report", "Report");
  const report = await waitForPreview(page);
  await expect(report.locator('[mo-value="metric"]')).toHaveText("42");

  const dashboardProjectRefresh = browserDiagnostics.expectResponseTransition(page, {
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/views\/dashboard\/project$/,
    failureStatus: 500,
    failureError: "configuration-error",
    successStatus: 200,
  });
  await selectView(page, "dashboard", "Studio browser fixture");
  const dashboardRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await replaceMetricCell(
    page,
    'metric = scale.value * 22\nresponsive_value = "responsive" * 80\nmetric',
  );
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain("scale.value * 22");
  dashboardProjectRefresh.seal();
  await expect((await waitForPreview(page)).locator('[mo-value="metric"]')).toHaveText("44");
  await recoverProjectionRefresh(dashboardRefresh, page);

  await selectView(page, "report", "Report");
  const reloadedReport = await waitForPreview(page);
  await expect(reloadedReport.locator('[mo-value="metric"]')).toHaveText("44");
  await recoverResponseTransition(dashboardProjectRefresh);
  await recoverRequestAbort(abandonedHandoffs);
  await recoverWorkspaceEventStream(replacedWorkspaceStreams);
  await editorModelRecovery.ready(page);
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
});
