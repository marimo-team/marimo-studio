import { expect, studioEntryUrl, test, waitForPreview } from "./fixture.ts";

test("opens Source in one click and retains the live preview through pane changes", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const notebook = page.getByRole("region", { name: "Notebook", exact: true });
  const app = page.getByRole("region", { name: "Preview", exact: true });
  const source = page.getByRole("region", { name: "Source", exact: true });
  await expect(source).toBeHidden();
  const notebookBounds = await notebook.boundingBox();
  const previewBounds = await app.boundingBox();
  expect(notebookBounds).not.toBeNull();
  expect(previewBounds).not.toBeNull();
  expect(notebookBounds!.width).toBe(previewBounds!.width);
  expect(notebookBounds!.height).toBe(previewBounds!.height);

  const retained = await preview.locator("body").elementHandle();
  const widget = preview.getByRole("button", { name: "Widget count: 7" });
  await widget.click();
  await expect(preview.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

  const toggle = page.getByRole("button", { name: "Toggle Source editor" });
  await toggle.click();
  await expect(source).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(await app.boundingBox()).toEqual(previewBounds);
  expect((await source.boundingBox())!.y).toBeGreaterThan((await notebook.boundingBox())!.y);

  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Move Source above Preview", exact: true }).click();
  expect((await source.boundingBox())!.x).toBe((await app.boundingBox())!.x);
  expect((await source.boundingBox())!.y).toBeLessThan((await app.boundingBox())!.y);
  await toggle.click();
  await expect(source).toBeHidden();
  expect(await app.boundingBox()).toEqual(previewBounds);
  expect(await retained!.evaluate((body) => body === document.body)).toBe(true);
  await expect(preview.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
});

test("keeps pane actions reachable in short panes and restores the saved arrangement", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  const source = page.getByRole("region", { name: "Source", exact: true });
  const divider = page.getByRole("separator", { name: "Resize rows" });
  await divider.focus();
  await divider.press("ArrowDown");
  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Swap with Preview", exact: true }).click();
  const saved = await source.boundingBox();
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Open saved layout", exact: true }).click();
  expect(await source.boundingBox()).toEqual(saved);

  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Close pane", exact: true }).click();
  await expect(source).toBeHidden();
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Restore workspace", exact: true }).click();
  await expect(page.getByRole("separator")).toHaveCount(1);
});

test("opens and closes Source directly at phone width", async ({ page }) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.setViewportSize({ width: 320, height: 720 });
  const surfaces = page.getByRole("navigation", { name: "Studio surface" });
  await surfaces.getByRole("button", { name: "Preview", exact: true }).click();
  const toggle = page.getByRole("button", { name: "Toggle Source editor" });
  await toggle.click();
  await expect(page.getByLabel("src/index.html source")).toBeVisible();
  await expect(surfaces.getByRole("button", { name: "Source", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await toggle.click();
  await expect(page.getByRole("region", { name: "Notebook", exact: true })).toBeVisible();
  await surfaces.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByRole("region", { name: "Preview", exact: true })).toBeVisible();
});
