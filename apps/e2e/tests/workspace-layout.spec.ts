import { executeCodeMode, studioEditorSessionId } from "./authoring-test-support.ts";
import {
  selectWorkspaceMode,
  expect,
  readWorkspaceFile,
  studioEntryUrl,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

test("native error notifications remain clickable over Preview and release it on dismissal", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const editor = page.frameLocator("iframe#marimo-studio-editor");
  await executeCodeMode(
    editor,
    "notebook.py",
    await studioEditorSessionId(page),
    "from marimo._messaging.notification import AlertNotification\n" +
      "from marimo._messaging.notification_utils import broadcast_notification\n" +
      'broadcast_notification(AlertNotification(title="Notebook error", description="Check the notebook inputs.", variant="danger"))',
  );
  const notification = editor
    .getByRole("region", { name: /Notifications/ })
    .getByRole("listitem")
    .filter({ hasText: "Notebook error" });
  await notification.hover();
  const notificationBounds = await notification.boundingBox();
  const previewBounds = await page
    .getByRole("region", { name: "Preview", exact: true })
    .boundingBox();
  expect(notificationBounds!.x + notificationBounds!.width).toBeGreaterThan(previewBounds!.x);
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  await page.setViewportSize({ width: 320, height: 720 });
  await notification.hover();
  await notification.locator("button[toast-close]").click();
  await expect(notification).toBeHidden();
  await expect(page.locator("#marimo-studio-root")).toHaveCSS("clip-path", "none");
  await page.getByRole("combobox", { name: "Visible surface" }).selectOption("preview");
  await preview.getByRole("button", { name: "Widget count: 7" }).click();
  await expect(preview.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
});

test("keeps the native table Explorer above the Studio toolbar", async ({ page }) => {
  const source = await readWorkspaceFile(workspaceNotebookPath);
  const visibleTable = source.replace(
    "    return (\n        alternate_summary,",
    "    rich_table\n    return (\n        alternate_summary,",
  );
  expect(visibleTable).not.toBe(source);
  await writeWorkspaceFile(workspaceNotebookPath, visibleTable);
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await selectWorkspaceMode(page, "Notebook");
  const editor = page.frameLocator("iframe#marimo-studio-editor");
  const richOutputs = editor.locator('[data-cell-name="rich_outputs"]');
  const table = richOutputs.locator("marimo-table");
  await table.scrollIntoViewIfNeeded();
  await table.getByText("Explore", { exact: true }).click();
  const explorer = editor.getByTestId("chrome-context-aware-panel");
  const toolbar = page.getByRole("banner", { name: "Studio" });
  await expect(explorer).toBeVisible();
  await expect(page.locator("iframe#marimo-studio-editor")).toHaveAttribute(
    "data-native-dialog",
    "",
  );
  const explorerBounds = await explorer.boundingBox();
  const toolbarBounds = await toolbar.boundingBox();
  expect(explorerBounds!.y).toBeLessThan(toolbarBounds!.y + toolbarBounds!.height);
  await editor.getByRole("button", { name: "Close selection panel" }).click();
  await expect(page.locator("iframe#marimo-studio-editor")).not.toHaveAttribute(
    "data-native-dialog",
    "",
  );
});

test("opens Source in one click and retains the live preview through pane changes", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const notebook = page.getByRole("region", { name: "Notebook", exact: true });
  const app = page.getByRole("region", { name: "Preview", exact: true });
  const source = page.getByRole("region", { name: "Source", exact: true });
  await expect(source).toBeHidden();
  const notebookBounds = await notebook.boundingBox();
  const previewBounds = await app.boundingBox();
  expect(notebookBounds).not.toBeNull();
  expect(previewBounds).not.toBeNull();
  expect(notebookBounds!.width).toBe(previewBounds!.width);
  expect(notebookBounds!.height).toBe(previewBounds!.height);

  const retained = await preview.locator("body").elementHandle();
  const widget = preview.getByRole("button", { name: "Widget count: 7" });
  await widget.click();
  await expect(preview.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

  const toggle = page.getByRole("button", { name: "Toggle Source editor" });
  await toggle.click();
  await expect(source).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(await notebook.boundingBox()).toEqual(notebookBounds);
  expect((await source.boundingBox())!.y).toBeGreaterThan((await app.boundingBox())!.y);

  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Arrange panes", exact: true }).click();
  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Move Source above Preview", exact: true }).click();
  expect((await source.boundingBox())!.x).toBe((await app.boundingBox())!.x);
  expect((await source.boundingBox())!.y).toBeLessThan((await app.boundingBox())!.y);
  await toggle.click();
  await expect(source).toBeHidden();
  expect(await app.boundingBox()).toEqual(previewBounds);
  expect(await retained!.evaluate((body) => body === document.body)).toBe(true);
  await expect(preview.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
});

test("keeps pane actions reachable in short panes and restores the saved arrangement", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  const source = page.getByRole("region", { name: "Source", exact: true });
  const divider = page.getByRole("separator", { name: "Resize rows" });
  await divider.focus();
  await divider.press("ArrowDown");
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Arrange panes", exact: true }).click();
  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Swap with Preview", exact: true }).click();
  const saved = await source.boundingBox();
  await selectWorkspaceMode(page, "Preview");
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Open saved layout", exact: true }).click();
  expect(await source.boundingBox()).toEqual(saved);

  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Arrange panes", exact: true }).click();
  await source.getByLabel("Arrange source pane").click();
  await source.getByRole("button", { name: "Close pane", exact: true }).click();
  await expect(source).toBeHidden();
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Restore workspace", exact: true }).click();
  await expect(page.getByRole("separator")).toHaveCount(1);
});

test("opens and closes Source directly at phone width", async ({ page }) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.setViewportSize({ width: 320, height: 720 });
  const surfaces = page.getByRole("combobox", { name: "Visible surface" });
  await surfaces.selectOption("preview");
  const toggle = page.getByRole("button", { name: "Toggle Source editor" });
  await toggle.click();
  await expect(page.getByLabel("src/index.html source")).toBeVisible();
  await expect(surfaces).toHaveValue("source");
  await toggle.click();
  await expect(page.getByRole("region", { name: "Notebook", exact: true })).toBeVisible();
  await surfaces.selectOption("preview");
  await expect(page.getByRole("region", { name: "Preview", exact: true })).toBeVisible();
});

test("keeps the native agent sidebar available beside the notebook, view, and source", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const editor = page.frameLocator("iframe#marimo-studio-editor");
  await editor.locator('[data-testid="chrome-sidebar"] [data-key="ai"]').press("Enter");
  const sidebar = editor.getByTestId("helper");
  await expect(sidebar).toBeVisible();
  const toolbar = page.getByRole("banner", { name: "Studio" });
  await expect.poll(async () => (await toolbar.boundingBox())!.x).toBeGreaterThan(300);
  const retainedSidebar = await sidebar.elementHandle();
  const controls = await editor.getByTestId("chrome-controls-top-right").boundingBox();
  const toolbarBounds = await toolbar.boundingBox();
  expect(controls!.y).toBeGreaterThanOrEqual(toolbarBounds!.y + toolbarBounds!.height);
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  await expect(page.getByRole("region", { name: "Source", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Show view beside notebook" }).click();
  await expect(editor.locator("#app")).toBeVisible();
  await expect(page.getByRole("region", { name: "Preview", exact: true })).toBeHidden();
  await expect(page.getByRole("region", { name: "Source", exact: true })).toBeHidden();
  await expect(sidebar).toBeVisible();
  await page.getByRole("button", { name: "Show view beside notebook" }).click();
  await expect(editor.locator("#app")).toBeVisible();
  await expect(page.getByRole("region", { name: "Source", exact: true })).toBeVisible();
  expect(await retainedSidebar!.evaluate((element) => element.isConnected)).toBe(true);
  await editor.getByTestId("close-helper-pane").click();
  await expect.poll(async () => (await toolbar.boundingBox())!.x).toBeLessThan(100);
  await expect(page.getByRole("region", { name: "Preview", exact: true })).toBeVisible();
});

test("reveals status context on hover and focus, then runtime details on click", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const status = page.getByLabel("Python preview runtime", { exact: true });
  await expect(status).toHaveText("Live");
  await status.hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText("dashboard · Python");
  await expect(tooltip).toContainText("editor's Python session");
  await status.focus();
  await status.press("Escape");
  await expect(tooltip).toBeHidden();
  await status.click();
  await expect(page.getByRole("status", { name: "Preview runtime status" })).toBeVisible();
  await page.frameLocator("iframe#marimo-studio-editor").locator(".cm-content").first().focus();
  await expect(page.getByRole("button", { name: /Browser/ })).toBeVisible();
  await expect(tooltip).toBeHidden();
  await status.press("Escape");
  await expect(page.getByRole("status", { name: "Preview runtime status" })).toBeHidden();
});
