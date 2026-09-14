import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import {
  expect,
  expectEditorModelReplayRecovery,
  retireWorkspacePage,
  test,
  waitForViewPreview,
  writeViewSource,
  workspaceCreatedViewHtmlPath,
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
  await page.getByRole("button", { name: "Focus Source", exact: true }).click();
  await expect(page.getByRole("tab", { name: "index.html" })).toBeVisible();
  const styleTab = page.getByRole("tab", { name: "styles/app.css" });
  const scriptTab = page.getByRole("tab", { name: "scripts/app.js" });
  await expect(styleTab).toBeVisible();
  await expect(scriptTab).toBeVisible();
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
});

test("retains the preview during filesystem edits and reconciles on release", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  test.setTimeout(240_000);
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await page.goto("/studio/vanilla-local/?file=notebook.py");
  const preview = await waitForViewPreview(page, "vanilla-local", "server", 120_000);
  await editorModelRecovery.ready(page);
  await expect(preview.getByRole("heading", { name: "Vanilla local sources" })).toBeVisible();
  const token = await studioCli.holdWorkspacePublication("vanilla-local");
  try {
    const path = workspaceCreatedViewHtmlPath("vanilla-local");
    const original = await readFile(path, "utf8");
    await writeFile(path, original.replace("Vanilla local sources", "Filesystem revision"));
    await writeFile(
      resolve(dirname(path), "scripts/app.js"),
      'document.documentElement.dataset.localScript = "filesystem";\n',
    );
    await expect(studioCli.buildWorkspaceView("vanilla-local")).rejects.toThrow(
      /Publication is held/,
    );
    await expect(preview.getByRole("heading", { name: "Vanilla local sources" })).toBeVisible();
    await expect(preview.locator("html")).toHaveAttribute("data-local-script", "ready");
  } finally {
    await studioCli.releaseWorkspacePublication("vanilla-local", token);
  }
  await expect(preview.getByRole("heading", { name: "Filesystem revision" })).toBeVisible({
    timeout: 120_000,
  });
  await expect(preview.locator("html")).toHaveAttribute("data-local-script", "filesystem");
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
});
