import {
  editorFrame,
  expect,
  expectPreviewInteractive,
  labeledSlider,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  sessionInventorySchema,
  studioEntryUrl,
  studioOrigin,
  studioServerToken,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
} from "./fixture.ts";

test("shares one native kernel across Studio tabs and views", async ({
  page,
  browserDiagnostics,
}) => {
  test.setTimeout(180_000);
  await page.goto(studioEntryUrl);
  const first = await waitForPreview(page);
  await first.getByRole("button", { name: "Widget count: 7" }).click();
  await expect(first.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

  const peer = await page.context().newPage();
  const otherView = await page.context().newPage();
  try {
    await peer.goto(studioEntryUrl);
    const second = await waitForPreview(peer);
    await expect(second.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    await expect(
      editorFrame(peer).getByRole("button", { name: "Take over", exact: true }),
    ).toBeVisible();
    await expect(
      editorFrame(page).getByRole("button", { name: "Take over", exact: true }),
    ).toHaveCount(0);
    await peer.locator('iframe[title="Marimo editor"]').evaluate(
      (editor: HTMLIFrameElement) =>
        new Promise<void>((resolve) => {
          editor.addEventListener("load", () => resolve(), { once: true });
          editor.contentWindow?.location.reload();
        }),
    );
    await expect(
      editorFrame(peer).getByRole("button", { name: "Take over", exact: true }),
    ).toBeVisible();
    await expect(
      editorFrame(page).getByRole("button", { name: "Take over", exact: true }),
    ).toHaveCount(0);
    await expect(second.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

    await otherView.goto(`${studioOrigin()}/studio/vanilla-local/?file=notebook.py`);
    const third = await waitForPreview(otherView);
    const token = await studioServerToken(page);
    const inventory = await page.request.post("/api/home/running_notebooks", {
      headers: { "Marimo-Server-Token": token },
    });
    expect(inventory.ok()).toBe(true);
    expect(sessionInventorySchema.parse(await inventory.json()).files).toHaveLength(1);

    await labeledSlider(first.locator('marimo-cell[name="controls"]'), /^Scale/).press("End");
    for (const preview of [first, second, third]) {
      await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");
    }
    await labeledSlider(second.locator('marimo-cell[name="controls"]'), /^Scale/).press("Home");
    for (const preview of [first, second, third]) {
      await expect(preview.locator('[mo-value="metric"]')).toHaveText("21");
    }
    await second.getByRole("button", { name: "Widget count: 8" }).click();
    await expect(first.getByRole("button", { name: "Widget count: 9" })).toBeVisible();

    await editorFrame(peer).getByRole("button", { name: "Take over", exact: true }).click();
    await expect(
      editorFrame(page).getByRole("button", { name: "Take over", exact: true }),
    ).toBeVisible();
    const retired = browserDiagnostics.expectPageRetirement(peer);
    await peer.close();
    retired.recovered();

    await labeledSlider(first.locator('marimo-cell[name="controls"]'), /^Scale/).press("End");
    await expect(third.locator('[mo-value="metric"]')).toHaveText("63");
    await first.getByRole("button", { name: "Widget count: 9" }).click();
    await expect(first.getByRole("button", { name: "Widget count: 10" })).toBeVisible();
    await expect(otherView.getByLabel("Switch view")).toContainText("vanilla-local");

    await otherView.getByLabel(/preview runtime$/).click();
    await otherView.getByRole("button", { name: /Browser/ }).click();
    const wasm = await waitForPreview(otherView, "wasm", WASM_PREVIEW_TIMEOUT);
    await expectPreviewInteractive(otherView, "wasm");
    await expect(wasm.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(first.locator('[mo-value="metric"]')).toHaveText("63");
    await otherView.getByLabel(/preview runtime$/).click();
    const controls = browserDiagnostics.expectRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: /^\/_marimo-studio\/views\/vanilla-local\/controls$/,
      count: 1,
      required: false,
    });
    await otherView.getByRole("button", { name: /Python/ }).click();
    await expectPreviewInteractive(otherView, "server");
    await recoverRequestAbort(controls);
    await expect(third.locator('[mo-value="metric"]')).toHaveText("63");

    const replacedStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
      `${studioOrigin()}/_marimo-studio/dev/events`,
    );
    await page.reload();
    const reloaded = await waitForPreview(page);
    await expect(reloaded.getByRole("button", { name: "Widget count: 10" })).toBeVisible();
    await expect(reloaded.locator('[mo-value="metric"]')).toHaveText("63");
    await recoverWorkspaceEventStream(replacedStream);
  } finally {
    await peer.close();
    const retired = browserDiagnostics.expectPageRetirement(otherView);
    await otherView.close();
    retired.recovered();
  }
});
