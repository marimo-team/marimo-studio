import { resolve } from "node:path";

import {
  addWorkspaceView,
  expect,
  presentationFrame,
  readWorkspaceFile,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeViewSource,
} from "./fixture.ts";

test("creates, projects into, and navigates a Reveal.js deck", async ({ page }) => {
  test.setTimeout(180_000);
  await addWorkspaceView(workspaceNotebookPath, "slides", "marimo-studio/react:reveal");

  await page.goto("/studio/slides/?file=notebook.py");
  let preview = await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Slides", level: 1 })).toBeVisible();

  const appPath = resolve(
    workspaceNotebookPath,
    "../__marimo__/studio/notebook/slides/src/App.tsx",
  );
  const source = await readWorkspaceFile(appPath);
  await writeViewSource(
    page,
    "slides",
    "src/App.tsx",
    source.replace(
      "      <h2>Place results in the argument</h2>",
      "      <h2>Place results in the argument</h2>\n" + '      <strong mo-value="metric" />',
    ),
  );

  preview = await waitForPreview(page);
  await preview.getByRole("button", { name: "next slide" }).click();
  await expect(
    preview.getByRole("heading", { name: "Place results in the argument" }),
  ).toBeVisible();
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");

  const popoutOpened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await popoutOpened;
  await popout.waitForLoadState("domcontentloaded");
  await popout.setViewportSize({ width: 390, height: 844 });
  const narrow = presentationFrame(popout);
  await expect(narrow.getByRole("heading", { name: "Slides", level: 1 })).toBeVisible();
  expect(
    await narrow.locator("html").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
  await popout.close();
});
