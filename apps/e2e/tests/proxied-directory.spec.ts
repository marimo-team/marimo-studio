import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { proxiedDirectoryNotebookPath } from "../scripts/paths.ts";
import {
  editorSlider,
  expect,
  expectPreviewRevisionSwap,
  labeledSlider,
  presentationFrame,
  proxiedDirectoryUrl,
  test,
  waitForPreview,
} from "./fixture.ts";

// A directory server selects each notebook through its `file` query. The proxy
// publishes it beneath a random /s/<id>/p/<id>/ prefix and strips that prefix.
// The browser fixture fails the test when any request leaves the prefix.
test.use({ services: ["proxiedDirectory"] });

test("serves directory views beneath a stripped proxy prefix", async ({ page }) => {
  const kernelStream = page.waitForRequest((request) =>
    new URL(request.url()).pathname.endsWith("/sse"),
  );
  await page.goto(`${proxiedDirectoryUrl()}?file=notebook.py`);
  // The directory server streams kernel messages over server-sent events.
  expect(new URL((await kernelStream).url()).pathname).toBe(
    `${new URL(proxiedDirectoryUrl()).pathname}_marimo-studio/editor/sse`,
  );

  await expect(page).toHaveURL(`${proxiedDirectoryUrl()}studio/dashboard/?file=notebook.py`);
  const preview = await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  await labeledSlider(preview.locator("body"), /^Proxied scale/).press("End");
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");
  await expect(editorSlider(page, /^Proxied scale/)).toHaveAttribute("aria-valuenow", "3");

  // A standalone edit-mode view attaches to the notebook session that Studio opened.
  const tab = await page.context().newPage();
  const view = presentationFrame(tab);
  await tab.goto(`${proxiedDirectoryUrl()}report/?file=notebook.py`);
  await expect(view.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  await expect(tab).toHaveURL(`${proxiedDirectoryUrl()}report/?file=notebook.py`);
  const report = view.getByRole("heading", { name: "Proxied report" });
  await expect(report).toBeVisible();
  // The authored stylesheet resolves against the artifact base beneath the prefix.
  await expect(report).toHaveCSS("color", "rgb(12, 34, 56)");
  await expect(view.getByRole("heading", { name: "Proxied total: 63" })).toBeVisible();

  await view.getByRole("link", { name: "Dashboard" }).click();
  await expect(tab).toHaveURL(`${proxiedDirectoryUrl()}dashboard/?file=notebook.py`);
  await expect(view.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  await expect(view.locator('[mo-value="metric"]')).toHaveText("63");
  await tab.close();
});

test("keeps an agent preview URL live on a directory server beneath a stripped proxy prefix", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await page.goto(`${proxiedDirectoryUrl()}?file=notebook.py`);
  await waitForPreview(page);

  const url = await studioCli.previewView(
    proxiedDirectoryNotebookPath,
    `${proxiedDirectoryUrl()}?file=notebook.py`,
    "report",
    "server",
  );

  expect(url.startsWith(`${proxiedDirectoryUrl()}report/?`)).toBe(true);
  expect(new URL(url).searchParams.get("file")).toBe("notebook.py");
  const tab = await page.context().newPage();
  await tab.goto(url);
  await expect(tab.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  const viewPath = new URL(`${proxiedDirectoryUrl()}report/`).pathname;
  expect(new URL(tab.url()).pathname).toBe(viewPath);
  await expect(tab.getByRole("heading", { name: "Proxied report" })).toBeVisible();

  const revisionSwap = expectPreviewRevisionSwap(
    browserDiagnostics,
    proxiedDirectoryUrl(),
    "report",
  );
  const source = resolve(
    dirname(proxiedDirectoryNotebookPath),
    "__marimo__/studio/notebook/report/index.html",
  );
  const original = await readFile(source, "utf8");
  try {
    await writeFile(source, original.replace("<h1>Proxied report</h1>", "<h1>Agent report</h1>"));

    await expect(tab.getByRole("heading", { name: "Agent report" })).toBeVisible({
      timeout: 65_000,
    });
    const live = new URL(tab.url());
    expect(live.pathname).toBe(viewPath);
    expect(live.searchParams.get("file")).toBe("notebook.py");
    await tab.close();
  } finally {
    // The directory server keeps its views for the worker's other tests.
    await writeFile(source, original);
  }
  await revisionSwap();
});
