import type { FrameLocator } from "@playwright/test";

import { readFile } from "node:fs/promises";

import {
  expect,
  recoverRequestAbort,
  studioOrigin,
  test,
  waitForPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

// Marimo serves both outputs as virtual files at ./@file/<name>, which the
// view resolves against its artifact revision. The Prepared runtime captures
// them as data URLs.
const resourcesCell = [
  "@app.cell",
  "def resources(mo):",
  "    import base64",
  "",
  "    _chip = base64.b64decode(",
  '        "iVBORw0KGgoAAAANSUhEUgAAACgAAAAUCAIAAABwJOjsAAAAJElEQVR42mPgUbIYEMQwavGoxaMWj1o8avGoxaMWj1o8ciwGAG+yPtAOirF5AAAAAElFTkSuQmCC"',
  "    )",
  "    mo.vstack(",
  "        [",
  '            mo.ui.data_editor({"name": ["Ada", "Grace"], "value": [1, 2]}),',
  '            mo.image(_chip, alt="Chip"),',
  "        ]",
  "    )",
  "    return",
  "",
  "",
  'if __name__ == "__main__":',
].join("\n");

const page = `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Resources</title></head>
  <body>
    <main id="app-shell">
      <marimo-cell name="resources"></marimo-cell>
    </main>
  </body>
</html>
`;

test("loads notebook virtual files in a view", async ({
  browserDiagnostics,
  page: browser,
  studioCli,
}) => {
  test.setTimeout(300_000);
  const notebook = await readFile(workspaceNotebookPath, "utf8");
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook
      .replace('# runtimes = ["server", "wasm"]', '# runtimes = ["server", "zero-python"]')
      .replace('if __name__ == "__main__":', resourcesCell),
  );
  await studioCli.addWorkspaceView(
    workspaceNotebookPath,
    "resources",
    "marimo-studio/vanilla:default",
  );
  await writeWorkspaceFile(workspaceCreatedViewHtmlPath("resources"), page);
  await studioCli.buildWorkspaceView("resources");

  await browser.goto("/studio/resources/?file=notebook.py");
  await expectResources(await waitForPreview(browser));

  await browser.getByLabel(/preview runtime$/).click();
  // Switching to Prepared can retire the zero-python manifest read that the
  // runtime frame started before the Prepared presentation replaced it.
  const retiredManifest = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin(),
    method: "GET",
    path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/resources\/zero-python\/current$/,
    count: 1,
    required: false,
    status: 200,
  });
  await browser.getByRole("button", { name: /^Prepared/ }).click();
  await expectResources(await waitForPreview(browser, "zero-python"));
  await recoverRequestAbort(retiredManifest);
});

const expectResources = async (preview: FrameLocator) => {
  const resources = preview.locator('marimo-cell[name="resources"]');
  // Glide draws editor rows on a canvas and mirrors them in an accessible grid.
  await expect(resources.locator('[role="gridcell"]', { hasText: "Grace" })).toHaveCount(1);
  const chip = resources.getByRole("img", { name: "Chip" });
  await expect.poll(() => chip.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(40);
};
