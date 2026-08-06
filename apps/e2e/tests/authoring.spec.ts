import { access } from "node:fs/promises";
import { resolve } from "node:path";

import {
  dashboardCssPath,
  dashboardHtmlPath,
  expect,
  previewFrame,
  readWorkspaceFile,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const saveShortcut = process.platform === "darwin" ? "Meta+s" : "Control+s";
const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";

test("keeps browser and disk source edits in sync", async ({ page }) => {
  await page.goto("/studio/dashboard/");
  const preview = await waitForPreview(page);
  const widgetButton = preview.getByRole("button", { name: /Widget count:/ });
  await expect(widgetButton).toHaveText(/^Widget count: \d+$/);
  const widgetCount = Number((await widgetButton.textContent())?.split(": ").at(-1));
  await widgetButton.click();
  await expect(widgetButton).toHaveText(`Widget count: ${widgetCount + 1}`);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "HTML & CSS" }).click();
  const sourceStatus = page.getByRole("region", { name: "HTML & CSS" }).getByRole("status");
  const previewElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  expect(previewElement).not.toBeNull();

  const initialCss = await readWorkspaceFile(dashboardCssPath);
  const externalCss = `${initialCss}\nbody { --e2e-marker: ready; }\n`;
  await writeWorkspaceFile(dashboardCssPath, externalCss);
  await expect
    .poll(() =>
      preview
        .locator("body")
        .evaluate((body) => getComputedStyle(body).getPropertyValue("--e2e-marker").trim()),
    )
    .toBe("ready");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const changed = source.replace("Studio browser fixture</h1>", "Edited in Studio</h1>");
  const htmlEditor = page.getByLabel("HTML source");
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(changed);
  await htmlEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardHtmlPath)).toBe(changed);
  await expect(sourceStatus).toHaveText("Saved ✓");
  await expect(preview.getByRole("heading", { name: "Edited in Studio" })).toBeVisible();

  const longSource = changed.replace(
    "</main>",
    `${Array.from({ length: 80 }, (_, index) => `<p>Scroll row ${index + 1}</p>`).join("\n")}</main>`,
  );
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(longSource);
  const htmlScroller = page.locator(".studio-source-editor:not([hidden]) .cm-scroller");
  expect(
    await htmlScroller.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return element.scrollTop > 0;
    }),
  ).toBe(true);
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(changed);
  await htmlEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardHtmlPath)).toBe(changed);
  await expect(sourceStatus).toHaveText("Saved ✓");

  await page.getByRole("tab", { name: "CSS" }).click();
  const cssEditor = page.getByLabel("CSS source");
  const cssSource = await readWorkspaceFile(dashboardCssPath);
  await expect(cssEditor).toContainText("--e2e-marker: ready");
  const longCss = `${cssSource}\n${Array.from(
    { length: 80 },
    (_, index) => `.row-${index + 1} { padding: ${index + 1}px; }`,
  ).join("\n")}`;
  await cssEditor.click();
  await cssEditor.press(selectAllShortcut);
  await page.keyboard.insertText(longCss);
  const cssScroller = page.locator(".studio-source-editor:not([hidden]) .cm-scroller");
  expect(
    await cssScroller.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return element.scrollTop > 0;
    }),
  ).toBe(true);
  await cssEditor.click();
  await cssEditor.press(selectAllShortcut);
  await page.keyboard.insertText(cssSource);
  await cssEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardCssPath)).toBe(cssSource);
  await expect(sourceStatus).toHaveText("Saved ✓");

  const currentPreviewElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [previewElement, currentPreviewElement],
    ),
  ).toBe(true);
  await expect(widgetButton).toHaveText(`Widget count: ${widgetCount + 1}`);
});

test("creates a scaffolded view and removes its files", async ({ page }) => {
  await page.goto("/studio/dashboard/");
  await waitForPreview(page);

  await page.getByLabel("Select or manage a view").click();
  await page.getByRole("button", { name: "+ New view" }).click();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Select or manage a view")).toContainText("qa-view");
  await expect(page.getByLabel("HTML source")).toBeVisible();
  const preview = previewFrame(page);
  await expect(preview.getByRole("heading", { name: "Qa View" })).toBeVisible();
  await expect(preview.locator("marimo-cell")).toHaveCount(5);

  const createdDirectory = resolve(workspaceNotebookPath, "../__marimo__/studio/notebook/qa-view");
  await expect.poll(async () => access(createdDirectory).then(() => true)).toBe(true);
  await page.getByLabel("Select or manage a view").click();
  await page.getByLabel("Remove qa-view view").click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.getByLabel("Select or manage a view")).toContainText("dashboard");
  await expect
    .poll(async () =>
      access(createdDirectory).then(
        () => true,
        () => false,
      ),
    )
    .toBe(false);
  await expect(
    previewFrame(page).getByRole("heading", { name: "Studio browser fixture" }),
  ).toBeVisible();
});
