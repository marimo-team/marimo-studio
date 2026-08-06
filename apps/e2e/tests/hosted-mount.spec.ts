import { readFile } from "node:fs/promises";

import {
  editorSlider,
  expect,
  hostedDashboardHtmlPath,
  hostedViewFixturePath,
  previewFrame,
  restoreHostedWorkspace,
  test,
  waitForPreview,
  writeWorkspaceFile,
} from "./fixture.ts";

const origin = "http://127.0.0.1:4322";
const baseUrl = `${origin}/hosted`;
const accessToken = "studio-e2e-token";

test.beforeEach(async () => {
  await restoreHostedWorkspace();
});

test("initializes and runs Studio through an authenticated hosted mount", async ({ page }) => {
  await expect
    .poll(
      async () =>
        fetch(`${baseUrl}/?access_token=${accessToken}`, { redirect: "manual" })
          .then((response) => response.status)
          .catch(() => 0),
      { timeout: 30_000 },
    )
    .toBe(303);

  await page.goto(`${baseUrl}/?access_token=${accessToken}`);
  await expect(page).toHaveURL(`${baseUrl}/`);
  await expect(page.getByRole("heading", { name: "Create the first view" })).toBeVisible();

  const before = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl}/_marimo-studio/status`);
  expect(before).toEqual({
    schema: 1,
    state: "needs-view",
    default_view: "dashboard",
    views: [],
  });

  await page.getByRole("button", { name: "Create dashboard" }).click();
  await expect(page).toHaveURL(`${baseUrl}/studio/dashboard/`);
  await expect(page.getByLabel("Select or manage a view")).toContainText("dashboard");

  const after = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl}/_marimo-studio/status`);
  expect(after).toEqual({
    schema: 1,
    state: "ready",
    default_view: "dashboard",
    views: ["dashboard"],
  });

  const preview = await waitForPreview(page);
  await writeWorkspaceFile(hostedDashboardHtmlPath, await readFile(hostedViewFixturePath, "utf8"));
  await expect(preview.getByRole("heading", { name: "Hosted mount lifecycle" })).toBeVisible();

  const scale = editorSlider(page);
  const value = previewFrame(page).locator('[mo-value="metric"]');
  await scale.press("Home");
  await expect(value).toHaveText("21");
  await scale.press("End");
  await expect(value).toHaveText("63");
});
