import {
  addWorkspaceView,
  buildWorkspaceView,
  expect,
  labeledSlider,
  presentationFrame,
  test,
  waitForPreview,
  workspaceNotebookPath,
} from "./fixture.ts";

test("creates, projects into, and navigates a Reveal.js deck", async ({ page }) => {
  test.setTimeout(180_000);
  await addWorkspaceView(workspaceNotebookPath, "slides", "marimo-studio/react:reveal");
  await buildWorkspaceView("slides");

  await page.goto("/studio/slides/?file=notebook.py");
  const preview = await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Notebook", level: 1 })).toBeVisible();

  await preview.getByRole("button", { name: "next slide" }).click();
  await expect(preview.getByRole("heading", { name: "Controls" })).toBeVisible();
  await expect(
    labeledSlider(preview.locator('marimo-cell[name="controls"]'), /^Scale/),
  ).toBeVisible();
  await preview.getByRole("button", { name: "next slide" }).click();
  await expect(preview.getByRole("heading", { name: "Metric" })).toBeVisible();
  await expect(preview.locator('marimo-cell[name="metric"]')).toContainText("42");
  await preview.getByRole("button", { name: "next slide" }).click();
  await expect(preview.getByRole("heading", { name: "Slow Metric" })).toBeVisible();
  await expect(preview.locator('marimo-cell[name="slow_metric"]')).toContainText("7");
  await preview.getByRole("button", { name: "next slide" }).click();
  await expect(preview.getByRole("heading", { name: "Counter Widget" })).toBeVisible();
  await expect(
    preview.locator('marimo-cell[name="counter_widget"]').getByRole("button"),
  ).toHaveText("Widget count: 7");

  const popoutOpened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await popoutOpened;
  try {
    await popout.waitForLoadState("domcontentloaded");
    await popout.setViewportSize({ width: 390, height: 844 });
    const narrow = presentationFrame(popout);
    await expect(narrow.getByRole("heading", { name: "Notebook", level: 1 })).toBeVisible();
    await narrow.getByRole("button", { name: "next slide" }).click();
    await expect(narrow.getByRole("heading", { name: "Controls" })).toBeVisible();
    await expect(
      labeledSlider(narrow.locator('marimo-cell[name="controls"]'), /^Scale/),
    ).toBeVisible();
    expect(
      await narrow
        .locator("html")
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
  } finally {
    await popout.close();
  }
});
