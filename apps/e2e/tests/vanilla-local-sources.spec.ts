import {
  expect,
  expectEditorModelReplayRecovery,
  retireWorkspacePage,
  test,
  waitForViewPreview,
  writeViewSource,
} from "./fixture.ts";

test("publishes Vanilla local CSS and JavaScript sources", async ({ browserDiagnostics, page }) => {
  test.setTimeout(240_000);
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await page.goto("/studio/vanilla-local/?file=notebook.py");
  const preview = await waitForViewPreview(page, "vanilla-local", "server", 120_000);
  await editorModelRecovery.ready(page);
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
    timeout: 120_000,
  });

  await writeViewSource(
    page,
    "vanilla-local",
    "scripts/app.js",
    'document.documentElement.dataset.localScript = "updated";\n',
  );
  await expect(root).toHaveAttribute("data-local-script", "updated", {
    timeout: 120_000,
  });

  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Source", exact: true }).click();
  await expect(page.getByRole("tab", { name: "index.html" })).toBeVisible();
  const styleTab = page.getByRole("tab", { name: "styles/app.css" });
  const scriptTab = page.getByRole("tab", { name: "scripts/app.js" });
  await expect(styleTab).toBeVisible();
  await expect(scriptTab).toBeVisible();
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
});
