import {
  expect,
  expectEditorModelReplayRecovery,
  test,
  waitForViewPreview,
  writeViewSource,
} from "./fixture.ts";

test("publishes Vanilla local CSS and JavaScript sources", async ({ browserDiagnostics, page }) => {
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await page.goto("/studio/vanilla-local/?file=notebook.py");
  const preview = await waitForViewPreview(page, "vanilla-local");
  await editorModelRecovery.recovered(page);
  const root = preview.locator("html");

  await expect(preview.getByRole("heading", { name: "Vanilla local sources" })).toBeVisible();
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(root).toHaveAttribute("data-local-script", "ready");
  await expect(preview.locator("body")).toHaveCSS("color", "rgb(68, 144, 255)");

  await writeViewSource(
    page,
    "vanilla-local",
    "styles/app.css",
    "body { color: rgb(34 197 94); }\n",
  );
  await expect(preview.locator("body")).toHaveCSS("color", "rgb(34, 197, 94)", {
    timeout: 65_000,
  });

  await writeViewSource(
    page,
    "vanilla-local",
    "scripts/app.js",
    'document.documentElement.dataset.localScript = "updated";\n',
  );
  await expect(root).toHaveAttribute("data-local-script", "updated", {
    timeout: 65_000,
  });

  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Source" }).click();
  await expect(page.getByRole("tab", { name: "index.html" })).toBeVisible();
  const styleTab = page.getByRole("tab", { name: "styles/app.css" });
  const scriptTab = page.getByRole("tab", { name: "scripts/app.js" });
  await expect(styleTab).toBeVisible();
  await expect(scriptTab).toBeVisible();
});
