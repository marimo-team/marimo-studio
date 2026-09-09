import { expect, studioEntryUrl, test, waitForPreview } from "./fixture.ts";

for (const theme of ["light", "dark"] as const) {
  test(`keeps the native ${theme} theme when the system preference differs`, async ({ page }) => {
    const system = theme === "light" ? "dark" : "light";
    await page.emulateMedia({ colorScheme: system });
    await page.goto(studioEntryUrl);
    await waitForPreview(page);
    const editorBody = page.frameLocator("#marimo-studio-editor").locator("body");
    await editorBody.evaluate((body, resolved) => {
      body.dataset.theme = resolved;
    }, system);
    const studio = page.locator(".studio[data-theme]");
    await expect(studio).toHaveAttribute("data-theme", system);
    const toolbar = page.locator(".studio-toolbar");
    const background = await toolbar.evaluate(
      (element) => getComputedStyle(element).backgroundColor,
    );

    await editorBody.evaluate((body, resolved) => {
      body.dataset.theme = resolved;
    }, theme);
    await expect(studio).toHaveAttribute("data-theme", theme);
    await expect
      .poll(() => toolbar.evaluate((element) => getComputedStyle(element).backgroundColor))
      .not.toBe(background);
  });
}
