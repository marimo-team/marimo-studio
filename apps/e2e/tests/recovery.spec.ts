import type { Page } from "@playwright/test";

import {
  editorFrame,
  expect,
  previewFrame,
  readWorkspaceFile,
  test,
  waitForPreview,
  workspaceNotebookPath,
} from "./fixture.ts";

const runShortcut = process.platform === "darwin" ? "Meta+Enter" : "Control+Enter";
const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";
const originalMetricSource = "metric = scale.value * 21\nmetric";

const replaceMetricCell = async (page: Page, source: string) => {
  const cell = editorFrame(page)
    .locator(".cm-content")
    .filter({ hasText: /(?:metric|replacement) = scale\.value \* 21/ })
    .first();
  await cell.click();
  await cell.press(selectAllShortcut);
  await page.keyboard.insertText(source);
  await page.keyboard.press(runShortcut);
};

const waitForMetricSource = () =>
  expect
    .poll(async () => {
      const source = await readWorkspaceFile(workspaceNotebookPath);
      return source.includes("metric = scale.value * 21") && !source.includes("replacement =");
    })
    .toBe(true);

test("restores a value host after its notebook value returns", async ({ page }) => {
  await page.goto("/studio/dashboard/");
  const preview = await waitForPreview(page);
  const value = preview.locator('[mo-value="metric"]');
  const initial = await value.textContent();
  expect(initial).toMatch(/^\d+$/);
  let restored = false;

  try {
    await replaceMetricCell(page, "replacement = scale.value * 21\nreplacement");

    await expect(value).toHaveAttribute("data-state", "error");
    await expect(preview.locator('marimo-cell[name="controls"]')).toHaveAttribute(
      "data-state",
      "ready",
    );
    expect(
      await preview.locator("html").evaluate(() => globalThis.marimoStudio.diagnostics()),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: expect.stringMatching(/^(missing-variable|value-variable-not-found)$/),
          severity: "error",
          target: "metric",
        }),
      ]),
    );

    await replaceMetricCell(page, originalMetricSource);
    await expect(value).toHaveAttribute("data-state", "ready");
    await waitForMetricSource();
    restored = true;
    await expect(value).toHaveText(initial ?? "");
    await expect(previewFrame(page).locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
  } finally {
    if (!restored) {
      await replaceMetricCell(page, originalMetricSource);
      await expect(value).toHaveAttribute("data-state", "ready");
      await waitForMetricSource();
    }
  }
});
