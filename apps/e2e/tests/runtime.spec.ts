import { editorSlider, expect, previewFrame, test, waitForPreview } from "./fixture.ts";

test("keeps one live frame per runtime while modes and controls change", async ({ page }) => {
  await page.goto("/studio/dashboard/");
  const server = await waitForPreview(page);
  const wasm = await waitForPreview(page, "wasm");
  const serverWidget = server.getByRole("button", { name: /Widget count:/ });
  await expect(serverWidget).toHaveText(/^Widget count: \d+$/);
  const serverWidgetCount = Number((await serverWidget.textContent())?.split(": ").at(-1));
  await serverWidget.click();
  await expect(serverWidget).toHaveText(`Widget count: ${serverWidgetCount + 1}`);
  await expect(page.getByRole("button", { name: "Build", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  const editorElement = await page.locator('iframe[title="Marimo editor"]').elementHandle();
  const serverElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const wasmElement = await page
    .locator('iframe[data-preview-runtime-frame="wasm"]')
    .elementHandle();
  expect(editorElement).not.toBeNull();
  expect(serverElement).not.toBeNull();
  expect(wasmElement).not.toBeNull();

  const scale = editorSlider(page);
  await scale.press("Home");
  await expect(server.locator('[mo-value="metric"]')).toHaveText("21");
  await expect(wasm.locator('[mo-value="metric"]')).toHaveText("21");
  await scale.press("End");
  await expect(server.locator('[mo-value="metric"]')).toHaveText("63");
  await expect(wasm.locator('[mo-value="metric"]')).toHaveText("63");

  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  const wasmWidget = wasm.getByRole("button", { name: /Widget count:/ });
  await expect(wasmWidget).toHaveText(/^Widget count: \d+$/);
  const wasmWidgetCount = Number((await wasmWidget.textContent())?.split(": ").at(-1));
  await wasmWidget.click();
  await expect(wasmWidget).toHaveText(`Widget count: ${wasmWidgetCount + 1}`);
  await expect(server.locator("button").filter({ hasText: /Widget count:/ })).toHaveText(
    `Widget count: ${serverWidgetCount + 1}`,
  );
  const wasmScale = wasm.getByRole("slider");
  await wasmScale.press("Home");
  await expect(scale).toHaveAttribute("aria-valuenow", "1");
  await expect(server.locator('[mo-value="metric"]')).toHaveText("21");
  await wasmScale.press("End");
  await expect(scale).toHaveAttribute("aria-valuenow", "3");
  await expect(server.locator('[mo-value="metric"]')).toHaveText("63");

  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  for (const mode of ["Notebook", "Preview", "Build", "Notebook", "Build"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
  }

  expect(await page.locator("iframe").count()).toBe(3);
  const currentEditor = await page.locator('iframe[title="Marimo editor"]').elementHandle();
  const currentServer = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const currentWasm = await page
    .locator('iframe[data-preview-runtime-frame="wasm"]')
    .elementHandle();
  expect(
    await page.evaluate(([before, after]) => before === after, [editorElement, currentEditor]),
  ).toBe(true);
  expect(
    await page.evaluate(([before, after]) => before === after, [serverElement, currentServer]),
  ).toBe(true);
  expect(
    await page.evaluate(([before, after]) => before === after, [wasmElement, currentWasm]),
  ).toBe(true);
  await expect(page.locator('iframe[data-preview-runtime-frame="server"]')).toBeVisible();
  await expect(page.locator('iframe[data-preview-runtime-frame="wasm"]')).toHaveAttribute(
    "inert",
    "",
  );
  await expect(serverWidget).toHaveText(`Widget count: ${serverWidgetCount + 1}`);
  await expect(wasm.locator("button").filter({ hasText: /Widget count:/ })).toHaveText(
    `Widget count: ${wasmWidgetCount + 1}`,
  );

  await page.setViewportSize({ width: 360, height: 800 });
  const compactNavigation = page.getByRole("navigation", { name: "Studio surface" });
  await expect(compactNavigation.getByRole("button", { name: "Notebook" })).toBeVisible();
  await expect(compactNavigation.getByRole("button", { name: "Preview" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await expect(previewFrame(page).locator('[mo-value="metric"]')).toHaveText("63");
});
