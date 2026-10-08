import type { FrameLocator } from "@playwright/test";

import { readFile } from "node:fs/promises";

import {
  expect,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const chartCell = [
  "@app.cell",
  "def chart():",
  "    from matplotlib.figure import Figure",
  "",
  "    chart = Figure(figsize=(4, 2.5))",
  "    chart.subplots().plot([1, 3, 2])",
  "    return (chart,)",
  "",
  "",
  'if __name__ == "__main__":',
].join("\n");

// `chart.figure` selects the same figure as `chart`, so one view can show the
// figure natively and as an accepted PNG side by side.
const page = `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><title>Media</title></head>
  <body>
    <main id="app-shell">
      <div id="native"><marimo-output value="chart"></marimo-output></div>
      <div id="png"><marimo-output value="chart.figure" accept="image/png"></marimo-output></div>
      <div id="svg"><marimo-output value="chart.axes[0]" accept="image/svg+xml"></marimo-output></div>
    </main>
  </body>
</html>
`;

const imageSize = async (preview: FrameLocator, host: string) => {
  const image = preview.locator(`#${host} marimo-output img`);
  await expect(image).toBeVisible();
  // A data URL decodes after the image becomes visible.
  await expect
    .poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBeGreaterThan(0);
  return image.evaluate((element: HTMLImageElement) => {
    const box = element.getBoundingClientRect();
    return { width: box.width, natural: element.naturalWidth };
  });
};

const expectNativeSize = async (preview: FrameLocator) => {
  const native = await imageSize(preview, "native");
  const png = await imageSize(preview, "png");
  const svg = await imageSize(preview, "svg");
  expect(png.width).toBeCloseTo(native.width, 0);
  expect(png.natural).toBeCloseTo(2 * png.width, -1);
  expect(svg.width).toBeGreaterThan(0.9 * native.width);
  expect(svg.width).toBeLessThan(1.1 * native.width);
};

test("shows an accepted PNG at the size marimo shows the figure", async ({
  page: browser,
  studioCli,
}) => {
  test.setTimeout(300_000);
  const notebook = await readFile(workspaceNotebookPath, "utf8");
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace('if __name__ == "__main__":', chartCell),
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "media", "marimo-studio/vanilla:default");
  await writeWorkspaceFile(workspaceCreatedViewHtmlPath("media"), page);
  await studioCli.buildWorkspaceView("media");

  await browser.goto("/studio/media/?file=notebook.py");
  await expectNativeSize(await waitForPreview(browser));

  await browser.getByLabel(/preview runtime$/).click();
  await browser.getByRole("button", { name: /Browser/ }).click();
  await expectNativeSize(await waitForPreview(browser, "wasm", WASM_PREVIEW_TIMEOUT));
});
