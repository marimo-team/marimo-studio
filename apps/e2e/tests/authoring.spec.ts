import { access } from "node:fs/promises";
import { resolve } from "node:path";

import {
  addWorkspaceView,
  bindWorkspaceCell,
  checkWorkspace,
  dashboardCssPath,
  dashboardHtmlPath,
  editorFrame,
  expect,
  plainDashboardHtmlPath,
  plainNotebookPath,
  previewFrame,
  readWorkspaceFile,
  studioEntryUrl,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const saveShortcut = process.platform === "darwin" ? "Meta+s" : "Control+s";
const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";

test("keeps browser and disk source edits in sync", async ({ page }) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const widgetButton = preview.getByRole("button", { name: /Widget count:/ });
  await expect(widgetButton).toHaveText(/^Widget count: \d+$/);
  const widgetCount = Number((await widgetButton.textContent())?.split(": ").at(-1));
  await widgetButton.click();
  await expect(widgetButton).toHaveText(`Widget count: ${widgetCount + 1}`);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "HTML & CSS" }).click();
  const sourceStatus = page.getByRole("region", { name: "HTML & CSS" }).getByRole("status");
  const previewElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  expect(previewElement).not.toBeNull();

  const initialCss = await readWorkspaceFile(dashboardCssPath);
  const externalCss = `${initialCss}\nbody { --e2e-marker: ready; }\n`;
  await writeWorkspaceFile(dashboardCssPath, externalCss);
  await expect
    .poll(() =>
      preview
        .locator("body")
        .evaluate((body) => getComputedStyle(body).getPropertyValue("--e2e-marker").trim()),
    )
    .toBe("ready");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const changed = source.replace("Studio browser fixture</h1>", "Edited in Studio</h1>");
  const htmlEditor = page.getByLabel("HTML source");
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(changed);
  await htmlEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardHtmlPath)).toBe(changed);
  await expect(sourceStatus).toHaveText("Saved ✓");
  await expect(preview.getByRole("heading", { name: "Edited in Studio" })).toBeVisible();

  const longSource = changed.replace(
    "</main>",
    `${Array.from({ length: 80 }, (_, index) => `<p>Scroll row ${index + 1}</p>`).join("\n")}</main>`,
  );
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(longSource);
  const htmlScroller = page.locator(".studio-source-editor:not([hidden]) .cm-scroller");
  expect(
    await htmlScroller.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return element.scrollTop > 0;
    }),
  ).toBe(true);
  await htmlEditor.click();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(changed);
  await htmlEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardHtmlPath)).toBe(changed);
  await expect(sourceStatus).toHaveText("Saved ✓");

  await page.getByRole("tab", { name: "CSS" }).click();
  const cssEditor = page.getByLabel("CSS source");
  const cssSource = await readWorkspaceFile(dashboardCssPath);
  await expect(cssEditor).toContainText("--e2e-marker: ready");
  const longCss = `${cssSource}\n${Array.from(
    { length: 80 },
    (_, index) => `.row-${index + 1} { padding: ${index + 1}px; }`,
  ).join("\n")}`;
  await cssEditor.click();
  await cssEditor.press(selectAllShortcut);
  await page.keyboard.insertText(longCss);
  const cssScroller = page.locator(".studio-source-editor:not([hidden]) .cm-scroller");
  expect(
    await cssScroller.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      return element.scrollTop > 0;
    }),
  ).toBe(true);
  await cssEditor.click();
  await cssEditor.press(selectAllShortcut);
  await page.keyboard.insertText(cssSource);
  await cssEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardCssPath)).toBe(cssSource);
  await expect(sourceStatus).toHaveText("Saved ✓");

  const currentPreviewElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [previewElement, currentPreviewElement],
    ),
  ).toBe(true);
  await expect(widgetButton).toHaveText(`Widget count: ${widgetCount + 1}`);
});

test("keeps configured aliases attached to edited notebook cells", async ({ page }) => {
  await bindWorkspaceCell("range-control", 1);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    source.replace('name="controls"', 'name="range-control"'),
  );

  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  await expect(preview.getByText("Scale", { exact: true })).toBeVisible();

  const editor = editorFrame(page);
  const controlCell = editor.getByRole("textbox").filter({ hasText: 'label="Scale"' });
  await expect(controlCell).toHaveCount(1);
  await controlCell.click();
  await controlCell.press(selectAllShortcut);
  await page.keyboard.insertText(`scale = mo.ui.slider(
    start=1,
    stop=3,
    value=2,
    show_value=True,
    label="Adjusted",
)
scale`);
  await page.keyboard.press("Shift+Enter");

  await expect(preview.getByText("Adjusted", { exact: true })).toBeVisible();
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain('label="Adjusted"');
  expect(await checkWorkspace()).toBe(true);
});

test("routes directory notebooks by Studio configuration", async ({ page }) => {
  await page.goto("/");
  const plainUrl = await page
    .getByRole("treeitem", { name: /plain\.py/ })
    .getByRole("link")
    .getAttribute("href");
  expect(plainUrl).not.toBeNull();
  await page.goto(plainUrl!);
  await expect(page).toHaveURL(/\?file=plain\.py$/);
  await expect(page.locator("#marimo-studio-bootstrap")).toHaveCount(0);

  await page.goto("/");
  const configuredUrl = await page
    .getByRole("treeitem", { name: /notebook\.py/ })
    .getByRole("link")
    .getAttribute("href");
  expect(configuredUrl).not.toBeNull();
  await page.goto(configuredUrl!);
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=notebook\.py$/);
  await expect(page.locator("#marimo-studio-bootstrap")).toBeAttached();
});

test("activates Studio after the first view is created", async ({ page }) => {
  const instantiated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
      response.ok(),
  );
  await page.goto("/?file=plain.py");
  await instantiated;
  await expect(page.locator("#marimo-studio-bootstrap")).toHaveCount(0);

  await addWorkspaceView(plainNotebookPath, "dashboard");
  const source = await readWorkspaceFile(plainDashboardHtmlPath);
  await writeWorkspaceFile(
    plainDashboardHtmlPath,
    source.replace(
      "</header>",
      '  <p id="papers"><span mo-value="summary.papers"></span> papers</p>\n      </header>',
    ),
  );

  await page.goto("/?file=plain.py");
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=plain\.py$/);
  const preview = await waitForPreview(page);
  await expect(preview.locator("#papers")).toHaveText("3877 papers");
});

test("loads a native module graph from a directory view", async ({ page }) => {
  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    source.replace(
      "</head>",
      '    <script type="module" src="scripts/app.js"></script>\n  </head>',
    ),
  );

  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);

  await expect
    .poll(() => preview.locator("html").getAttribute("data-module-status"))
    .toBe("Native module ready");
});

test("keeps nested authored content inside a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  const responsive = source.replace(
    /<main id="app-shell"[\s\S]*<\/main>/,
    `<main id="app-shell">
      <section style="display: grid; grid-template-columns: minmax(0, 1fr)">
        <div style="display: grid; grid-template-columns: minmax(0, 1fr)">
          <code
            data-responsive-scroll
            style="display: block; overflow: auto; white-space: nowrap"
          ><span
            mo-value="responsive_value"
            style="display: inline-block; min-width: max-content; white-space: nowrap"
          ></span></code>
        </div>
      </section>
    </main>`,
  );

  await writeWorkspaceFile(dashboardHtmlPath, responsive);
  const value = preview.locator('[mo-value="responsive_value"]');
  await expect(value).toContainText("responsiveresponsive");

  expect(
    await preview.locator("html").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
});

test("keeps relative view navigation public and reconnectable", async ({ page }) => {
  await page.goto(`${studioEntryUrl}&region=eu`);
  await waitForPreview(page);

  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    source.replace(
      /<main id="app-shell"([^>]*)>/,
      `<main id="app-shell"$1>
        <nav>
          <a href="#details">View details</a>
          <a href="?region=us">Use US region</a>
          <a href="../qa-view/">Open QA view</a>
        </nav>
        <section id="details">Quarterly details</section>`,
    ),
  );
  await page.getByLabel("Select or manage a view").click();
  await page.getByRole("button", { name: "+ New view" }).click();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const direct = await page.context().newPage();
  const directErrors: string[] = [];
  direct.on("pageerror", (error) => directErrors.push(error.message));
  direct.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) {
      directErrors.push(message.text());
    }
  });
  const waitForDirectView = async () => {
    await expect(direct.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(direct.getByRole("button", { name: "Widget count: 7" })).toBeVisible();
  };

  try {
    await direct.goto("/dashboard/?file=notebook.py&region=eu");
    await waitForDirectView();
    await direct.getByRole("link", { name: "View details" }).click();
    await expect(direct).toHaveURL(/\/dashboard\/\?file=notebook\.py&region=eu#details$/);
    await direct.getByRole("link", { name: "Use US region" }).click();
    await expect(direct).toHaveURL(/\/dashboard\/\?file=notebook\.py&region=us$/);
    await waitForDirectView();
    await direct.getByRole("link", { name: "Open QA view" }).click();
    await expect(direct).toHaveURL(/\/qa-view\/\?file=notebook\.py&region=us$/);
    await expect(direct.getByRole("heading", { name: "Qa View" })).toBeVisible();
    await waitForDirectView();
    await direct.reload();
    await waitForDirectView();
    await expect(direct.getByRole("heading", { name: "Qa View" })).toBeVisible();
    const fileToken = Buffer.from("notebook.py").toString("base64url");
    await direct.goto(`/_marimo-studio/notebooks/${fileToken}/views/dashboard/?region=apac`);
    await expect(direct).toHaveURL(/\/dashboard\/\?file=notebook\.py&region=apac$/);
    await waitForDirectView();
    expect(directErrors).toEqual([]);
  } finally {
    await direct.close();
  }
});

test("creates a scaffolded view and removes its files", async ({ page }) => {
  const deletedViewRequests: string[] = [];
  let removalStarted = false;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (removalStarted && url.pathname.includes("/qa-view/")) {
      deletedViewRequests.push(request.url());
    }
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);

  await page.getByLabel("Select or manage a view").click();
  await page.getByRole("button", { name: "+ New view" }).click();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Select or manage a view")).toContainText("qa-view");
  await expect(page.getByLabel("HTML source")).toBeVisible();
  const preview = previewFrame(page);
  await expect(preview.getByRole("heading", { name: "Qa View" })).toBeVisible();
  await expect(preview.locator("marimo-cell")).toHaveCount(5);

  const createdDirectory = resolve(workspaceNotebookPath, "../__marimo__/studio/notebook/qa-view");
  await expect.poll(async () => access(createdDirectory).then(() => true)).toBe(true);
  await page.getByLabel("Select or manage a view").click();
  await page.getByLabel("Remove qa-view view").click();
  removalStarted = true;
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.getByLabel("Select or manage a view")).toContainText("dashboard");
  await expect
    .poll(async () =>
      access(createdDirectory).then(
        () => true,
        () => false,
      ),
    )
    .toBe(false);
  await expect(
    previewFrame(page).getByRole("heading", { name: "Studio browser fixture" }),
  ).toBeVisible();
  expect(deletedViewRequests).toEqual([]);
});
