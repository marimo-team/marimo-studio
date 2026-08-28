import type { Page } from "@playwright/test";

import {
  expect,
  recoverRequestAbort,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
} from "./fixture.ts";

const presentationIdentity = async (page: Page) =>
  await (
    await waitForPreview(page)
  )
    .locator("html")
    .evaluate(() => globalThis.marimoStudio.identity());

test("refreshes a projected cached view after the view catalog changes", async ({
  browserDiagnostics,
  page,
}) => {
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    2,
  );
  await page.goto(studioEntryUrl);

  const dashboard = await waitForPreview(page);
  const projectedTable = dashboard.locator('marimo-output[value="rich_table"]');
  await expect(dashboard.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(projectedTable).toHaveAttribute("data-state", "ready");
  await expect(projectedTable.getByRole("button", { name: "Columns" })).toBeVisible();
  const initialIdentity = await presentationIdentity(page);
  const cachedDashboardFrame = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  if (!cachedDashboardFrame) {
    throw new Error("The dashboard preview frame did not mount");
  }
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 2,
    status: 204,
  });

  await page.getByLabel("Switch page").click();
  await page.getByRole("button", { name: "New page" }).click();
  await page.getByRole("radio", { name: /HTML document/ }).check();
  await page.getByLabel("New page").fill("catalog-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Switch page")).toContainText("catalog-view");
  await expect(
    (await waitForPreview(page)).getByRole("heading", { name: "Catalog View" }),
  ).toBeVisible();

  await page.getByLabel("Switch page").click();
  await page.getByRole("button", { name: "dashboard, default", exact: true }).click();
  await expect(page.getByLabel("Switch page")).toContainText("dashboard");

  const refreshedDashboard = await waitForPreview(page);
  const refreshedTable = refreshedDashboard.locator('marimo-output[value="rich_table"]');
  await expect(refreshedDashboard.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(refreshedTable).toHaveAttribute("data-state", "ready");
  await refreshedTable.getByRole("button", { name: "Columns" }).click();
  await expect(refreshedTable.getByRole("button", { name: "Columns" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  const refreshedIdentity = await presentationIdentity(page);
  const refreshedDashboardFrame = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  if (!refreshedDashboardFrame) {
    throw new Error("The cached dashboard preview frame did not reactivate");
  }
  expect(refreshedIdentity.revision).not.toBe(initialIdentity.revision);
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [cachedDashboardFrame, refreshedDashboardFrame],
    ),
  ).toBe(true);
  await recoverRequestAbort(abandonedHandoffs);
  replacedWorkspaceStreams.recovered();
});
