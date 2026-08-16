import {
  dashboardHtmlPath,
  editorFrame,
  editorSlider,
  expect,
  previewFrame,
  readWorkspaceFile,
  studioEntryUrl,
  test,
  waitForPreview,
  writeWorkspaceFile,
} from "./fixture.ts";

test("preserves native output state across HTML edits and replaces terminal failures", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const wasm = await waitForPreview(page, "wasm");
  const runtimeMarker = "projected-output-runtime";
  await wasm.locator("html").evaluate((_html, marker) => {
    globalThis.__e2eRuntimeMarker = marker;
  }, runtimeMarker);
  const expectWasmRuntimePreserved = async () => {
    await expect
      .poll(() => wasm.locator("html").evaluate(() => globalThis.__e2eRuntimeMarker))
      .toBe(runtimeMarker);
  };
  const serverSummary = server.locator("#rich-summary-output");
  const wasmSummary = wasm.locator("#rich-summary-output");
  const serverTable = server.locator('marimo-output[value="rich_table"]');
  const wasmTable = wasm.locator('marimo-output[value="rich_table"]');
  const serverLongOutput = server.locator("#long-output");
  const wasmLongOutput = wasm.locator("#long-output");
  const columns = serverTable.getByRole("button", { name: "Columns" });
  const wasmColumns = wasmTable.getByRole("button", { name: "Columns" });
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmSummary).toHaveAttribute("data-state", "ready");
  await expect(serverLongOutput).toContainText("Long selector ready");
  await expect(wasmLongOutput).toContainText("Long selector ready");
  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await wasmColumns.click();
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");
  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  await columns.click();
  await expect(columns).toHaveAttribute("aria-expanded", "true");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const layoutEdit = source.replace("Studio browser fixture</h1>", "Edited layout</h1>");
  await writeWorkspaceFile(dashboardHtmlPath, layoutEdit);
  await expect(server.getByRole("heading", { name: "Edited layout" })).toBeVisible();
  await expect(columns).toHaveAttribute("aria-expanded", "true");
  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await expect(wasm.getByRole("heading", { name: "Edited layout" })).toBeVisible();
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");

  const withoutSummary = layoutEdit.replace(
    '      <marimo-output id="rich-summary-output" value="rich_summary"></marimo-output>\n',
    "",
  );
  await writeWorkspaceFile(dashboardHtmlPath, withoutSummary);
  await expect(wasmSummary).toHaveCount(0);
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");
  await expectWasmRuntimePreserved();
  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  await expect(serverSummary).toHaveCount(0);
  await expect(columns).toHaveAttribute("aria-expanded", "true");

  await writeWorkspaceFile(dashboardHtmlPath, layoutEdit);
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(columns).toHaveAttribute("aria-expanded", "true");
  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await expect(wasmSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");
  await expectWasmRuntimePreserved();

  const alternate = layoutEdit.replace('value="rich_summary"', 'value="alternate_summary"');
  await writeWorkspaceFile(dashboardHtmlPath, alternate);
  await expect(wasmSummary.locator("h3")).toHaveText("Alternate total: 42");
  await expectWasmRuntimePreserved();
  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  await expect(serverSummary.locator("h3")).toHaveText("Alternate total: 42");

  const unavailable = layoutEdit.replace('value="rich_summary"', 'value="missing_output"');
  await writeWorkspaceFile(dashboardHtmlPath, unavailable);
  await expect(serverSummary).toHaveAttribute("data-state", "error");
  await expect(serverSummary).not.toContainText("Current total");
  await expect(serverSummary).toContainText("has no defining cell");
  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await expect(wasmSummary).toHaveAttribute("data-state", "error");
  await expect(wasmSummary).not.toContainText("Current total");
  await expect(wasmSummary).toContainText("has no defining cell");
  await expectWasmRuntimePreserved();

  await writeWorkspaceFile(dashboardHtmlPath, source);
  await expect(wasmSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 42");
  await expectWasmRuntimePreserved();
  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 42");
});

test("preserves projected controls across refresh and owner removal", async ({ page }) => {
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const wasm = await waitForPreview(page, "wasm");
  const serverFresh = server.locator("#fresh-control").getByRole("slider");
  const wasmFresh = wasm.locator("#fresh-control").getByRole("slider");
  const serverMixed = server.locator("#mixed-controls").getByRole("slider");
  const wasmMixed = wasm.locator("#mixed-controls").getByRole("slider");
  const serverSharedOwner = server.locator("#shared-control-owner");
  const wasmSharedOwner = wasm.locator("#shared-control-owner");

  await expect(serverFresh).toHaveAttribute("aria-valuenow", "2");
  await expect(serverMixed).toHaveCount(2);
  await expect(serverSharedOwner).toHaveAttribute("data-state", "ready");

  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "2");
  await expect(wasmMixed).toHaveCount(2);
  await expect(wasmSharedOwner).toHaveAttribute("data-state", "ready");
  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();

  await serverMixed.nth(1).press("End");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  const scale = editorSlider(page);
  await scale.press("Home");
  await expect(serverFresh).toHaveAttribute("aria-valuenow", "1");
  await expect(serverMixed.nth(0)).toHaveAttribute("aria-valuenow", "1");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  await page.getByLabel("Server preview runtime").click();
  await page.getByRole("button", { name: /WebAssembly/ }).click();
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "1");
  await expect(wasmMixed.nth(0)).toHaveAttribute("aria-valuenow", "1");
  await expect(wasmMixed.nth(1)).toHaveAttribute("aria-valuenow", "1");
  await wasmMixed.nth(1).press("End");

  await scale.press("End");
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "3");
  await expect(wasmMixed.nth(0)).toHaveAttribute("aria-valuenow", "3");
  await expect(wasmMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  await page.getByLabel("WebAssembly preview runtime").click();
  await page.getByRole("button", { name: /Server/ }).click();
  await expect(serverFresh).toHaveAttribute("aria-valuenow", "3");
  await expect(serverMixed.nth(0)).toHaveAttribute("aria-valuenow", "3");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const withoutOwner = source.replace(
    '      <marimo-output id="shared-control-owner" value="projected_control"></marimo-output>\n',
    "",
  );
  await writeWorkspaceFile(dashboardHtmlPath, withoutOwner);

  for (const [index, preview] of [server, wasm].entries()) {
    if (index > 0) {
      await page.getByLabel("Server preview runtime").click();
      await page.getByRole("button", { name: /WebAssembly/ }).click();
    }
    const owner = preview.locator("#shared-control-owner");
    const consumer = preview.locator("#shared-control-consumer");
    const peer = preview.locator("#shared-control-peer");
    await expect(owner).toHaveCount(0);
    await expect(consumer).toHaveAttribute("data-state", "ready");
    await expect(peer).toHaveAttribute("data-state", "ready");
    await preview.locator("html").evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );
    const slider = consumer.getByRole("slider");
    await slider.press("End");
    await expect(slider).toHaveAttribute("aria-valuenow", "3");
    await expect(peer.getByRole("slider")).toHaveAttribute("aria-valuenow", "3");
  }
});

test("keeps one live frame per runtime while modes and controls change", async ({ page }) => {
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const wasm = await waitForPreview(page, "wasm");
  const serverWidget = server.getByRole("button", { name: /Widget count:/ });
  const serverSummary = server.locator('marimo-output[value="rich_summary"]');
  const wasmSummary = wasm.locator('marimo-output[value="rich_summary"]');
  const serverTable = server.locator('marimo-output[value="rich_table"]');
  const wasmTable = wasm.locator('marimo-output[value="rich_table"]');
  const serverLongOutput = server.locator("#long-output");
  const wasmLongOutput = wasm.locator("#long-output");
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmSummary).toHaveAttribute("data-state", "ready");
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 42");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 42");
  await expect(serverTable).toContainText("Current total");
  await expect(wasmTable).toContainText("Current total");
  await expect(serverLongOutput).toContainText("Long selector ready");
  await expect(wasmLongOutput).toContainText("Long selector ready");
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
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 21");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 21");
  await expect(serverTable).toContainText("21");
  await expect(wasmTable).toContainText("21");

  const failOutputs = editorFrame(page).getByLabel("Fail projected outputs");
  await failOutputs.click();
  await expect(serverSummary).toHaveAttribute("data-state", "error");
  await expect(wasmSummary).toHaveAttribute("data-state", "error");
  await expect(serverSummary).not.toContainText("Current total");
  await expect(wasmSummary).not.toContainText("Current total");
  await expect(serverTable).toHaveAttribute("data-state", "error");
  await expect(wasmTable).toHaveAttribute("data-state", "error");
  await failOutputs.click();
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 21");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 21");
  await scale.press("End");
  await expect(server.locator('[mo-value="metric"]')).toHaveText("63");
  await expect(wasm.locator('[mo-value="metric"]')).toHaveText("63");
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 63");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 63");
  await expect(serverTable).toContainText("63");
  await expect(wasmTable).toContainText("63");
  await expect(serverLongOutput).toContainText("Long selector ready");
  await expect(wasmLongOutput).toContainText("Long selector ready");
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
  const wasmScale = wasm.locator('marimo-cell[name="controls"]').getByRole("slider");
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

test("keeps native output ownership isolated between server preview consumers", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const embedded = await waitForPreview(page);
  const popoutOpened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await popoutOpened;
  await popout.waitForLoadState("domcontentloaded");
  await expect
    .poll(() =>
      popout.evaluate(async () => {
        if (!globalThis.marimoStudio) {
          return false;
        }
        return Promise.race([
          globalThis.marimoStudio.ready().then(() => true),
          new Promise<false>((resolve) => setTimeout(() => resolve(false), 500)),
        ]);
      }),
    )
    .toBe(true);

  const embeddedTable = embedded.locator('marimo-output[value="rich_table"]');
  const popoutTable = popout.locator('marimo-output[value="rich_table"]');
  await embeddedTable.getByRole("button", { name: "Columns" }).click();
  await popoutTable.getByRole("button", { name: "Columns" }).click();
  await expect(embeddedTable.getByRole("button", { name: "Columns" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(popoutTable.getByRole("button", { name: "Columns" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  await editorSlider(page).press("End");
  await expect(embeddedTable).toContainText("63");
  await expect(popoutTable).toContainText("63");
  await popout.locator("#rich-summary-output").evaluate((host) => host.remove());
  await expect(embedded.locator("#rich-summary-output")).toHaveAttribute("data-state", "ready");

  await popout.close();
  const embeddedColumns = embeddedTable.getByRole("button", { name: "Columns" });
  await embeddedColumns.click();
  await expect(embeddedColumns).toHaveAttribute("aria-expanded", "true");
});
