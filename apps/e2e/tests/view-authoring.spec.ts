import { viewListSchema } from "@marimo-studio/protocol/views";
import { access } from "node:fs/promises";
import { resolve } from "node:path";

import {
  executeCodeMode,
  saveShortcut,
  selectAllShortcut,
  studioEditorSessionId,
} from "./authoring-test-support.ts";
import {
  dashboardHtmlPath,
  editorFrame,
  expect,
  expectEditorModelReplayRecovery,
  expectSupersededRenewalConfig,
  labeledSlider,
  plainDashboardHtmlPath,
  presentationFrame,
  previewFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  retireWorkspacePage,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
  waitForViewPreview,
  workspaceNotebookPath,
  writeDashboardSource,
  writeViewSource,
} from "./fixture.ts";

test("routes directory notebooks by Studio configuration", async ({ browserDiagnostics, page }) => {
  const directoryLandingFilenameFallback = browserDiagnostics.expectConsole({
    type: "warning",
    text: /^No filename provided, using fallback$/,
    count: 1,
  });
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    1,
  );
  const retiredPlainHealth = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/editor\/health$/,
    count: 1,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  await page.goto("/");
  const plainUrl = await page
    .getByRole("treeitem", { name: /plain\.py/ })
    .getByRole("link")
    .getAttribute("href");
  const configuredUrl = await page
    .getByRole("treeitem", { name: /notebook\.py/ })
    .getByRole("link")
    .getAttribute("href");
  expect(plainUrl).not.toBeNull();
  expect(configuredUrl).not.toBeNull();
  await page.goto(plainUrl!);
  await expect(page).toHaveURL(/\?file=plain\.py$/);
  await expect(editorFrame(page).getByText("Native Marimo notebook").first()).toBeVisible();

  await page.goto(configuredUrl!);
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=notebook\.py$/);
  await expect(
    (await waitForPreview(page)).getByRole("heading", { name: "Studio browser fixture" }),
  ).toBeVisible();
  directoryLandingFilenameFallback.recovered();
  retiredPlainHealth.recovered();
  await recoverWorkspaceEventStream(replacedWorkspaceStream);
});

test("activates Studio after the first view is created", async ({ browserDiagnostics, page }) => {
  const supersededConfig = expectSupersededRenewalConfig(browserDiagnostics, "dashboard");
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    1,
  );
  const instantiated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
      response.ok(),
  );
  await page.goto("/?file=plain.py&region=before&discard=clear-me");
  const instantiateResponse = await instantiated;
  await expect(editorFrame(page).getByText("Native Marimo notebook").first()).toBeVisible();

  const sessionId = instantiateResponse.request().headers()["marimo-session-id"];
  expect(sessionId).toBeTruthy();
  await editorFrame(page).locator(".cm-content").first().focus();

  await executeCodeMode(
    editorFrame(page),
    "plain.py",
    sessionId,
    `
import marimo as mo
import marimo_studio.agent as studio_agent

mo.query_params().clear()
mo.query_params().set("region", "eu")
workspace = studio_agent.current_workspace()
view = await workspace.create_view("dashboard")
shown = await view.show()
shown.to_dict()
`,
  );
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=plain\.py&region=eu$/);
  expect(await studioEditorSessionId(page)).toBe(sessionId);
  await expect(editorFrame(page).locator(".cm-content").first()).toBeFocused();
  const preview = await waitForPreview(page);
  await expect(preview.getByText("Native Marimo notebook")).toBeVisible();

  const source = await readWorkspaceFile(plainDashboardHtmlPath);
  const projectedSource = source.replace(
    "</header>",
    '  <p id="papers"><span mo-value="summary.papers"></span> papers</p>\n      </header>',
  );
  await writeViewSource(page, "dashboard", "index.html", projectedSource, "plain.py");

  await waitForPreview(page);
  await expect(preview.locator("#papers")).toHaveText("3877 papers", { timeout: 65_000 });
  await recoverWorkspaceEventStream(replacedWorkspaceStreams);
  supersededConfig.recovered();
});

test("opens Studio from the first save with the native session", async ({
  browserDiagnostics,
  page,
}) => {
  const filenameFallback = browserDiagnostics.expectConsole({
    type: "warning",
    text: /^No filename provided, using fallback$/,
    required: false,
  });
  const unusedPreload = browserDiagnostics.expectConsole({
    type: "warning",
    text: /^The resource .* was preloaded using link preload but not used/,
    required: false,
  });
  const dialogDescription = browserDiagnostics.expectConsole({
    type: "warning",
    text: /Missing `Description` or `aria-describedby=\{undefined\}` for \{DialogContent\}/,
    required: false,
  });
  const instantiated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
      response.ok(),
  );
  await page.goto("/?file=__new__s_first1&region=eu");
  const instantiateResponse = await instantiated;
  const sessionId = instantiateResponse.request().headers()["marimo-session-id"];
  expect(sessionId).toBeTruthy();

  const cell = page.locator("[data-cell-id]").first();
  await cell.getByRole("textbox").fill("saved = True\nsaved");
  await cell.hover();
  await cell.locator('button[data-testid="run-button"]:not(:disabled)').click();
  await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
  await page.getByTestId("save-button").click();
  const filename = page.getByPlaceholder("filename");
  await filename.fill("first-save.py");
  await page.getByText("Save as: first-save.py", { exact: true }).click();

  await expect(page.locator("#marimo-studio-host")).toBeAttached();
  filenameFallback.recovered();
  unusedPreload.recovered();
  dialogDescription.recovered();
  await expect(page).toHaveURL(/\/\?file=first-save\.py&region=eu$/);
  await expect(editorFrame(page).locator(".cm-content").first()).toContainText("saved = True");

  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    1,
  );
  await executeCodeMode(
    editorFrame(page),
    "first-save.py",
    sessionId,
    `
import marimo_studio.agent as studio_agent

workspace = studio_agent.current_workspace()
view = await workspace.create_view("dashboard")
await view.show()
`,
  );
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=first-save\.py&region=eu$/);
  expect(await studioEditorSessionId(page)).toBe(sessionId);
  await waitForPreview(page);
  replacedWorkspaceStream.recovered();
});

test("loads a native module graph from a directory view", async ({ browserDiagnostics, page }) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const supersededDocument = browserDiagnostics.expectActiveRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/presentation\/d\.[A-Za-z0-9._-]+\/dashboard\/$/,
    count: 1,
  });
  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeDashboardSource(
    page,
    source.replace(
      "</head>",
      '    <script type="module" src="scripts/app.js"></script>\n  </head>',
    ),
  );

  await expect
    .poll(() => preview.locator("html").getAttribute("data-module-status"))
    .toBe("Native module ready");
  await recoverRequestAbort(supersededDocument);
});

test("publishes a framework edit and retains the last good view across a failed build", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  test.setTimeout(300_000);
  await studioCli.addWorkspaceView(
    workspaceNotebookPath,
    "react-view",
    "marimo-studio/react:default",
  );
  await studioCli.buildWorkspaceView("react-view");

  const completedSourceWrites = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "PUT",
    path: /^\/_marimo-studio\/views\/react-view\/source\/src\/App\.tsx$/,
    count: 3,
    required: false,
    status: 204,
  });
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  await page.goto("/studio/react-view/?file=notebook.py");
  const preview = await waitForViewPreview(page, "react-view", "server", 120_000);
  await expect(preview.getByRole("heading", { name: "React View" })).toBeVisible();
  await expect(
    labeledSlider(preview.locator('marimo-cell[name="controls"]'), /^Scale/),
  ).toBeVisible();
  await expect(preview.getByRole("button", { name: "Widget count: 7" })).toBeVisible();

  const sourceTab = page.getByRole("tab", { name: "src/App.tsx" });
  if (!(await sourceTab.isVisible())) {
    await page.getByLabel("Workspace options").click();
    await page.getByRole("button", { name: "Source" }).click();
  }
  await sourceTab.click();
  const editor = page.getByLabel("src/App.tsx source");
  const path = resolve(
    workspaceNotebookPath,
    "../__marimo__/studio/notebook/react-view/src/App.tsx",
  );
  const source = await readWorkspaceFile(path);
  expect(source).toContain("React View");
  const initialRevision = await preview
    .locator("html")
    .evaluate(() => globalThis.marimoStudio.identity().revision);
  const goodSource = source.replace("React View", "React source published");

  await editor.focus();
  await editor.press(selectAllShortcut);
  await page.keyboard.insertText(goodSource);
  await editor.press(saveShortcut);

  await expect(page.getByRole("status", { name: "Source document status" })).toHaveText("Saved");
  await expect.poll(() => readWorkspaceFile(path)).toBe(goodSource);
  await expect(preview.getByRole("heading", { name: "React source published" })).toBeVisible({
    timeout: 65_000,
  });
  await waitForViewPreview(page, "react-view");
  await expect
    .poll(() => preview.locator("html").evaluate(() => globalThis.marimoStudio.identity().revision))
    .not.toBe(initialRevision);
  await expect(page.getByLabel("View build details, Up to date")).toBeVisible();

  const invalidSource = goodSource.replace(
    "export const App = () => (",
    "export const App = () => (BROKEN",
  );
  await editor.focus();
  await editor.press(selectAllShortcut);
  await page.keyboard.insertText(invalidSource);
  await editor.press(saveShortcut);

  await expect(page.getByLabel("View build details, Build failed")).toBeVisible();
  const diagnostic = page.getByRole("alert").filter({ hasText: "React provider" });
  await expect(diagnostic).toContainText("Expected");
  await expect(diagnostic).toContainText("src/App.tsx");
  await expect(preview.getByRole("heading", { name: "React source published" })).toBeVisible();

  await editor.focus();
  await editor.press(selectAllShortcut);
  await page.keyboard.insertText(goodSource);
  await editor.press(saveShortcut);
  await expect(page.getByLabel("View build details, Up to date")).toBeVisible();
  await expect(preview.getByRole("heading", { name: "React source published" })).toBeVisible();
  await expect(diagnostic).toHaveCount(0);

  await expect(page.getByRole("status", { name: "Source document status" })).toHaveText("Saved");
  await editorModelRecovery.ready(page);
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
  await recoverRequestAbort(completedSourceWrites);
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

  await writeDashboardSource(page, responsive);
  const value = preview.locator('[mo-value="responsive_value"]');
  await expect(value).toContainText("responsiveresponsive");

  expect(
    await preview.locator("html").evaluate((element) => element.scrollWidth <= element.clientWidth),
  ).toBe(true);
});

test("keeps relative navigation public across direct view reloads", async ({
  browserDiagnostics,
  page,
}) => {
  const abandonedHandoff = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 1,
    required: false,
    status: 204,
  });
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    1,
  );
  await page.goto(`${studioEntryUrl}&region=eu`);
  await waitForPreview(page);

  const navigationSource = `<!doctype html>
<html lang="en">
  <head><meta charset="utf-8" /><title>Navigation fixture</title></head>
  <body>
    <main id="app-shell">
      <h1>Navigation fixture</h1>
        <nav>
          <a href="#details">View details</a>
          <a href="?region=us">Use US region</a>
          <a href="../qa-view/index.html?region=apac#app-shell">Open QA view</a>
        </nav>
        <section id="details">Quarterly details</section>
    </main>
  </body>
</html>`;
  await writeDashboardSource(page, navigationSource);
  await expect(previewFrame(page).getByRole("link", { name: "View details" })).toBeVisible();
  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "New view" }).click();
  await page.getByRole("radio", { name: /HTML document/ }).check();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page).toHaveURL(/\/studio\/qa-view\/\?/);
  const qaHtmlPath = resolve(
    workspaceNotebookPath,
    "../__marimo__/studio/notebook/qa-view/index.html",
  );
  const qaSource = await readWorkspaceFile(qaHtmlPath);
  await writeViewSource(
    page,
    "qa-view",
    "index.html",
    qaSource.replace(
      /<main id="app-shell"([^>]*)>/,
      `<main id="app-shell"$1><strong id="query-region" mo-value='query_params["region"]'></strong>`,
    ),
  );
  const direct = await page.context().newPage();
  const directDocument = () =>
    direct.locator("iframe#marimo-studio-presentation").getAttribute("src");
  const waitForDirectView = async (previousDocument?: string | null) => {
    const rendered = presentationFrame(direct);
    const readState = async () => {
      const documentUrl = await directDocument();
      return rendered.locator("html").evaluate(
        (html, documentChanged) => ({
          documentChanged,
          state: html.dataset.marimoStudioState,
          diagnostics: globalThis.marimoStudio?.diagnostics() ?? [],
          projections: globalThis.marimoStudio?.projections() ?? [],
        }),
        previousDocument === undefined || documentUrl !== previousDocument,
      );
    };
    try {
      await expect
        .poll(() => readState())
        .toMatchObject({
          documentChanged: true,
          state: "ready",
        });
    } catch (error) {
      const current = await readState().catch(() => ({
        documentChanged: false,
        state: "unavailable",
      }));
      throw new Error(`Direct view did not become ready: ${JSON.stringify(current)}`, {
        cause: error,
      });
    }
  };
  const navigateDirectView = async (name: string, expectedUrl: RegExp, replacesDocument = true) => {
    const previousDocument = await directDocument();
    await presentationFrame(direct).getByRole("link", { name }).click();
    await expect(direct).toHaveURL(expectedUrl);
    await waitForDirectView(replacesDocument ? previousDocument : undefined);
  };

  try {
    await direct.goto("/dashboard/?file=notebook.py&region=eu");
    await waitForDirectView();
    await expect(presentationFrame(direct).locator("base")).toHaveAttribute(
      "href",
      /\/_marimo-studio\/artifacts\/[0-9a-f]{64}\/src\/$/,
    );
    await navigateDirectView(
      "View details",
      /\/dashboard\/\?file=notebook\.py&region=eu#details$/,
      false,
    );
    await navigateDirectView("Use US region", /\/dashboard\/\?file=notebook\.py&region=us$/);
    await navigateDirectView(
      "Open QA view",
      /\/qa-view\/\?file=notebook\.py&region=apac#app-shell$/,
    );
    await expect(presentationFrame(direct).getByRole("heading", { name: "Qa View" })).toBeVisible();
    const previousDocument = await directDocument();
    await direct.reload();
    await waitForDirectView(previousDocument);
    await expect(presentationFrame(direct).getByRole("heading", { name: "Qa View" })).toBeVisible();
    await recoverRequestAbort(abandonedHandoff);
    replacedWorkspaceStream.recovered();
  } finally {
    await direct.close();
  }
});

test("creates a view and removes its files", async ({ browserDiagnostics, page }) => {
  test.setTimeout(180_000);
  const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    2,
  );
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 2,
    required: false,
    status: 204,
  });
  const initialWorkspaceStream = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.status() === 200 &&
      response.request().resourceType() === "eventsource" &&
      url.pathname === "/_marimo-studio/dev/events"
    );
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await initialWorkspaceStream;

  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "New view" }).click();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Switch view")).toContainText("qa-view", {
    timeout: 65_000,
  });
  await expect(page.getByRole("tab", { name: "index.html" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByLabel("index.html source")).toBeVisible();
  const preview = await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Qa View" })).toBeVisible();
  await expect(preview.locator('marimo-cell[name="controls"]')).toBeVisible();

  const createdDirectory = resolve(workspaceNotebookPath, "../__marimo__/studio/notebook/qa-view");
  await expect.poll(async () => access(createdDirectory).then(() => true)).toBe(true);
  const supersededDashboardRenewal = browserDiagnostics.expectActiveRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/presentation\/d\.[A-Za-z0-9._-]+\/dashboard\/$/,
    count: 1,
  });
  await page.getByLabel("Switch view").click();
  const qaView = page.getByRole("button", { name: "qa-view", exact: true });
  const removeQaView = page.getByLabel("Remove qa-view view");
  await qaView.hover();
  await removeQaView.click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(page.getByLabel("Switch view")).toContainText("dashboard");
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
  await recoverRequestAbort(abandonedHandoffs);
  await recoverRequestAbort(supersededDashboardRenewal);
  await recoverWorkspaceEventStream(replacedWorkspaceStreams);
  await editorModelRecovery.ready(page);
  await retireWorkspacePage(page, browserDiagnostics);
  editorModelRecovery.recovered();
});

test.describe("touch input", () => {
  test.use({ hasTouch: true });

  test("keeps view removal directly available without hover", async ({
    browserDiagnostics,
    page,
  }) => {
    const editorModelRecovery = expectEditorModelReplayRecovery(browserDiagnostics);
    await page.goto(studioEntryUrl);
    await waitForPreview(page);
    await page.getByLabel("Switch view").tap();
    await page.getByLabel("Remove vanilla-local view").tap();

    const confirmation = page.getByRole("region", { name: "Remove view?" });
    await expect(confirmation).toContainText(
      "This permanently deletes the vanilla-local view and its files.",
    );
    await page.getByRole("button", { name: "Cancel" }).tap();
    await expect(page.getByLabel("Remove vanilla-local view")).toBeFocused();
    await editorModelRecovery.ready(page);
    await retireWorkspacePage(page, browserDiagnostics);
    editorModelRecovery.recovered();
  });
});

test("keeps a large view and starter catalog usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.route("**/_marimo-studio/views*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const inventory = viewListSchema.parse(await response.json());
    const viewSeed = inventory.views[0];
    const starterSeed = inventory.starters[0];
    const extraViews = Array.from({ length: 16 }, (_, index) => ({
      ...viewSeed,
      name: `view-${String(index + 1).padStart(2, "0")}`,
    }));
    const extraStarters = Array.from({ length: 8 }, (_, index) => ({
      ...starterSeed,
      id: `e2e-catalog/starter:e2e-${String(index + 1).padStart(2, "0")}`,
      title: `Starter ${String(index + 1).padStart(2, "0")}`,
    }));
    await route.fulfill({
      response,
      json: {
        ...inventory,
        default_starter: extraStarters[0]!.id,
        views: [viewSeed, ...extraViews],
        starters: [...extraStarters, ...inventory.starters],
      },
    });
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.getByLabel("Switch view").click();
  await expect(page.getByRole("button", { name: "view-16", exact: true })).toBeAttached();

  await page.getByRole("button", { name: "New view" }).click();
  const externalStarters = page.getByRole("group", {
    name: "From marimo-studio-e2e-provider",
    exact: true,
  });
  const bundledStarters = page.getByRole("group", {
    name: "From marimo-studio",
    exact: true,
  });
  await expect(externalStarters).toContainText("External report");
  await expect(externalStarters).toContainText("E2E web project");
  await expect(bundledStarters).toContainText("React");
  await expect(bundledStarters).toContainText("Svelte");
  await expect(bundledStarters).toContainText("HTML document");
  const input = page.getByLabel("New view");
  await expect(input).toBeFocused();
  await expect(input).toBeInViewport();
  const bounds = await input.evaluate((element) => {
    if (!(element instanceof HTMLInputElement) || !element.form) {
      throw new Error("New view input has no form owner");
    }
    const rectangle = element.form.getBoundingClientRect();
    return {
      left: rectangle.left,
      right: rectangle.right,
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: globalThis.innerWidth,
    };
  });
  expect(bounds.left).toBeGreaterThanOrEqual(0);
  expect(bounds.right).toBeLessThanOrEqual(bounds.viewportWidth);
  expect(bounds.scrollWidth).toBeLessThanOrEqual(bounds.viewportWidth);

  await input.press("Tab");
  const radios = page.getByRole("radio");
  await expect(radios.first()).toBeFocused();
  await radios.first().press("ArrowUp");
  await expect(radios.last()).toBeFocused();
  await expect(radios.last()).toBeChecked();
  await expect(radios.last().locator("..")).toBeInViewport();
  await radios.last().press("Tab");
  const details = page.getByText("Files created", { exact: true });
  await expect(details).toBeFocused();
  await details.press("Tab");
  const cancel = page.getByRole("button", { name: "Cancel" });
  await expect(cancel).toBeFocused();
  await expect(cancel).toBeInViewport();
});
