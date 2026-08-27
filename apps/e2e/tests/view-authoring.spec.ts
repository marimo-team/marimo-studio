import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { studioBootstrapSchema } from "@marimo-studio/protocol/studio-bootstrap";
import { viewListSchema } from "@marimo-studio/protocol/views";
import { access } from "node:fs/promises";
import { resolve } from "node:path";

import { saveShortcut, selectAllShortcut } from "./authoring-test-support.ts";
import {
  addWorkspaceView,
  dashboardHtmlPath,
  editorFrame,
  expect,
  plainDashboardHtmlPath,
  plainNotebookPath,
  presentationFrame,
  previewFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeDashboardSource,
  writeViewSource,
} from "./fixture.ts";

declare global {
  var __e2eBuildStatusObserver: MutationObserver | undefined;
  var __e2eBuildStatuses: string[] | undefined;
  var __e2eSourceStatuses: string[] | undefined;
}

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
  await expect(page.locator("#marimo-studio-bootstrap")).toHaveCount(0);
  await expect(editorFrame(page).getByText("Native Marimo notebook").first()).toBeVisible();

  await page.goto(configuredUrl!);
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=notebook\.py$/);
  await expect(page.locator("#marimo-studio-bootstrap")).toBeAttached();
  directoryLandingFilenameFallback.recovered();
  replacedWorkspaceStream.recovered();
});

test("activates Studio after the first view is created", async ({ browserDiagnostics, page }) => {
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    2,
  );
  const instantiated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
      response.ok(),
  );
  await page.goto("/?file=plain.py&region=before&discard=clear-me");
  const instantiateResponse = await instantiated;
  await expect(page.locator("#marimo-studio-bootstrap")).toHaveCount(0);
  await expect(page.locator("#marimo-studio-host")).toBeAttached();
  await expect(editorFrame(page).getByText("Native Marimo notebook").first()).toBeVisible();

  const sessionId = instantiateResponse.request().headers()["marimo-session-id"];
  expect(sessionId).toBeTruthy();
  const editorElement = await page.locator('iframe[title="Marimo editor"]').elementHandle();
  expect(editorElement).not.toBeNull();
  const retainedEditorSource = await page
    .locator('iframe[title="Marimo editor"]')
    .getAttribute("src");
  if (!retainedEditorSource) {
    throw new Error("The retained Marimo editor URL is unavailable.");
  }
  const editorTimeOrigin = await editorFrame(page)
    .locator("html")
    .evaluate(() => performance.timeOrigin);
  const initialEditorLocation = await editorFrame(page)
    .locator("html")
    .evaluate(() => location.href);
  const retainedEditor = new URL(retainedEditorSource, page.url());
  const initialEditor = new URL(initialEditorLocation);
  expect(retainedEditor.searchParams.get("session_id")).toBe(sessionId);
  expect(initialEditor.searchParams.has("session_id")).toBe(false);
  await editorFrame(page).locator(".cm-content").first().focus();

  const execution = editorFrame(page)
    .locator("html")
    .evaluate(async (_, activeSessionId) => {
      const response = await fetch("/_marimo-studio/editor/api/kernel/execute?file=plain.py", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Session-Id": activeSessionId,
        },
        body: JSON.stringify({
          code: `
import marimo as mo
import marimo_studio.agent as studio

mo.query_params().clear()
mo.query_params().set("region", "eu")
workspace = studio.open()
view = await workspace.create_view("dashboard")
activation = await view.activate()
activation.to_dict()
`,
        }),
      });
      return { ok: response.ok, text: await response.text() };
    }, sessionId);

  const result = await execution;
  expect(result.ok).toBe(true);
  expect(result.text).toContain('"success": true');
  await expect(page).toHaveURL(/\/studio\/dashboard\/\?file=plain\.py&region=eu$/);
  await expect(page.locator("#marimo-studio-bootstrap")).toBeAttached();
  const bootstrap = studioBootstrapSchema.parse(
    JSON.parse((await page.locator("#marimo-studio-bootstrap").textContent()) ?? ""),
  );
  const configuredEditorUrl = new URL(bootstrap.urls.editor, page.url()).href;
  const editorLocation = await editorFrame(page)
    .locator("html")
    .evaluate(() => location.href);
  const activeEditor = new URL(editorLocation);
  const configuredEditor = new URL(configuredEditorUrl);
  expect(configuredEditor.origin).toBe(retainedEditor.origin);
  expect(configuredEditor.pathname).toBe(retainedEditor.pathname);
  expect(activeEditor.origin).toBe(configuredEditor.origin);
  expect(activeEditor.pathname).toBe(configuredEditor.pathname);
  for (const key of [
    "file",
    "marimo_studio_client",
    "marimo_studio_server",
    "marimo_studio_editor",
  ]) {
    expect(initialEditor.searchParams.get(key)).toBe(retainedEditor.searchParams.get(key));
    expect(configuredEditor.searchParams.get(key)).toBe(retainedEditor.searchParams.get(key));
    expect(activeEditor.searchParams.get(key)).toBe(retainedEditor.searchParams.get(key));
  }
  expect(configuredEditor.searchParams.get("session_id")).toBe(sessionId);
  expect(activeEditor.searchParams.has("session_id")).toBe(false);
  expect(activeEditor.searchParams.get("marimo_studio_editor")).toBeTruthy();
  const configuredPublicQuery = new URLSearchParams(publicNotebookQuery(configuredEditor.search));
  const activePublicQuery = new URLSearchParams(publicNotebookQuery(activeEditor.search));
  configuredPublicQuery.sort();
  activePublicQuery.sort();
  expect([...configuredPublicQuery]).toEqual([...activePublicQuery]);
  expect(configuredEditor.searchParams.get("region")).toBe("eu");
  expect(configuredEditor.searchParams.has("discard")).toBe(false);
  expect(activeEditor.searchParams.get("region")).toBe("eu");
  expect(activeEditor.searchParams.has("discard")).toBe(false);
  expect(
    await editorFrame(page)
      .locator("html")
      .evaluate(() => performance.timeOrigin),
  ).toBe(editorTimeOrigin);
  expect(
    await page
      .locator('iframe[title="Marimo editor"]')
      .evaluate((frame, original) => frame === original, editorElement),
  ).toBe(true);
  const editorFocus = await editorFrame(page)
    .locator("html")
    .evaluate(() => ({
      preserved: document.activeElement?.classList.contains("cm-content") ?? false,
      activeTag: document.activeElement?.tagName,
    }));
  expect(editorFocus).toEqual({
    preserved: true,
    activeTag: "DIV",
  });
  const preview = await waitForPreview(page);

  const source = await readWorkspaceFile(plainDashboardHtmlPath);
  const projectedSource = source.replace(
    "</header>",
    '  <p id="papers"><span mo-value="summary.papers"></span> papers</p>\n      </header>',
  );
  await writeViewSource(page, "dashboard", "index.html", projectedSource, "plain.py");

  await waitForPreview(page);
  await expect(preview.locator("#papers")).toHaveText("3877 papers");

  await page.getByRole("button", { name: "Notebook", exact: true }).click();
  const editor = editorFrame(page);
  const existingCell = editor.locator("[data-cell-id]").first();
  await existingCell.hover();
  const createButtons = existingCell.getByTestId("create-cell-button").locator(":visible");
  await expect(createButtons).toHaveCount(2);
  await createButtons.last().click();
  const addedCell = editor.locator('[data-cell-name="_"]').last();
  const addedEditor = addedCell.getByRole("textbox");
  await addedEditor.click();
  await addedEditor.fill("fresh_value = 99\nfresh_value");
  await addedCell.hover();
  await addedCell.locator('button[data-testid="run-button"]:not(:disabled)').click();
  await expect(addedCell.locator("..")).toHaveAttribute("data-status", "idle");
  await expect.poll(() => readWorkspaceFile(plainNotebookPath)).toContain("fresh_value = 99");

  await page.getByRole("button", { name: "Develop", exact: true }).click();
  await writeViewSource(
    page,
    "dashboard",
    "index.html",
    projectedSource.replace(
      "</main>",
      '  <p>Fresh value: <strong id="fresh-value" mo-value="fresh_value"></strong></p>\n    </main>',
    ),
    "plain.py",
  );
  await waitForPreview(page);
  await expect(preview.locator("#fresh-value")).toHaveText("99");
  replacedWorkspaceStreams.recovered();
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

test("publishes visible edits from each built-in source model", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(180_000);
  await addWorkspaceView(workspaceNotebookPath, "html-view", "marimo-studio/vanilla:default");
  await addWorkspaceView(workspaceNotebookPath, "react-view", "marimo-studio/react:default");
  await addWorkspaceView(workspaceNotebookPath, "svelte-view", "marimo-studio/svelte:default");

  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const abandonedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 4,
    status: 204,
  });
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    4,
  );
  const completedSourceWrites = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "PUT",
    path: /^\/_marimo-studio\/views\/(?:html-view\/source\/index\.html|react-view\/source\/src\/App\.tsx|svelte-view\/source\/src\/App\.svelte)$/,
    count: 5,
    required: false,
    status: 204,
  });
  const cases = [
    {
      after: "HTML source published",
      before: "Html View",
      path: "index.html",
      view: "html-view",
    },
    {
      after: "React source published",
      before: "React View",
      path: "src/App.tsx",
      view: "react-view",
    },
    {
      after: "Svelte source published",
      before: "Svelte View",
      path: "src/App.svelte",
      view: "svelte-view",
    },
  ] as const;
  for (const candidate of cases) {
    await test.step(`${candidate.view} edit`, async () => {
      await page.getByLabel("Switch view").click();
      const option = page.getByRole("button", { name: candidate.view, exact: true });
      await option.click();
      const preview = await waitForPreview(page);
      await expect(preview.getByRole("heading", { name: candidate.before })).toBeVisible();

      await page.getByLabel("Workspace options").click();
      await page.getByRole("button", { name: "Source" }).click();
      await page.getByRole("tab", { name: candidate.path }).click();
      const editor = page.getByLabel(`${candidate.path} source`);
      const sourcePath = resolve(
        workspaceNotebookPath,
        "../__marimo__/studio/notebook",
        candidate.view,
        candidate.path,
      );
      const source = await readWorkspaceFile(sourcePath);
      expect(source).toContain(candidate.before);
      const initialRevision = await preview
        .locator("html")
        .evaluate(() => globalThis.marimoStudio.identity().revision);

      await page.evaluate(() => {
        globalThis.__e2eBuildStatusObserver?.disconnect();
        globalThis.__e2eBuildStatuses = [];
        globalThis.__e2eSourceStatuses = [];
        const record = () => {
          const label = document
            .querySelector<HTMLElement>('[aria-label^="View build details,"]')
            ?.getAttribute("aria-label");
          if (label && !globalThis.__e2eBuildStatuses?.includes(label)) {
            globalThis.__e2eBuildStatuses?.push(label);
          }
          const sourceStatus = document
            .querySelector<HTMLElement>('[role="status"][aria-label="Source document status"]')
            ?.textContent?.trim();
          if (sourceStatus && globalThis.__e2eSourceStatuses?.at(-1) !== sourceStatus) {
            globalThis.__e2eSourceStatuses?.push(sourceStatus);
          }
        };
        const observer = new MutationObserver(record);
        observer.observe(document.body, {
          attributeFilter: ["aria-label"],
          attributes: true,
          childList: true,
          subtree: true,
        });
        globalThis.__e2eBuildStatusObserver = observer;
        record();
      });

      await editor.focus();
      await editor.press(selectAllShortcut);
      const changedSource = source.replace(candidate.before, candidate.after);
      await page.keyboard.insertText(changedSource);
      await editor.press(saveShortcut);

      await expect(page.getByRole("status", { name: "Source document status" })).toHaveText(
        "Saved",
      );
      await expect.poll(() => readWorkspaceFile(sourcePath)).toBe(changedSource);
      await expect(preview.getByRole("heading", { name: candidate.after })).toBeVisible();
      await waitForPreview(page);
      await expect
        .poll(() =>
          preview.locator("html").evaluate(() => globalThis.marimoStudio.identity().revision),
        )
        .not.toBe(initialRevision);
      await expect(page.getByLabel("View build details, Up to date")).toBeVisible();
      const buildStatuses = await page.evaluate(() => globalThis.__e2eBuildStatuses ?? []);
      const sourceStatuses = await page.evaluate(() => globalThis.__e2eSourceStatuses ?? []);
      expect(sourceStatuses).toContain("Saving…");
      expect(sourceStatuses.at(-1)).toBe("Saved");
      expect(
        buildStatuses.some((status) =>
          ["View build details, Checking build", "View build details, Building"].includes(status),
        ),
      ).toBe(true);
    });
  }

  await test.step("failed framework build retains and explains the last good view", async () => {
    await page.getByLabel("Switch view").click();
    await page.getByRole("button", { name: "react-view", exact: true }).click();
    const preview = await waitForPreview(page);
    await expect(preview.getByRole("heading", { name: "React source published" })).toBeVisible();
    await page.getByRole("tab", { name: "src/App.tsx" }).click();
    const editor = page.getByLabel("src/App.tsx source");
    const path = resolve(
      workspaceNotebookPath,
      "../__marimo__/studio/notebook/react-view/src/App.tsx",
    );
    const goodSource = await readWorkspaceFile(path);
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
  });

  await page.evaluate(() => globalThis.__e2eBuildStatusObserver?.disconnect());
  await recoverRequestAbort(abandonedHandoffs);
  replacedWorkspaceStreams.recovered();
  await expect(page.getByRole("status", { name: "Source document status" })).toHaveText("Saved");
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
          <a href="../qa-view/?region=apac#app-shell">Open QA view</a>
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
  await page.goto(studioEntryUrl);
  await waitForPreview(page);

  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "New view" }).click();
  await page.getByLabel("New view").fill("qa-view");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Switch view")).toContainText("qa-view");
  await expect(page.getByRole("tab", { name: "index.html" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByLabel("index.html source")).toBeVisible();
  const preview = await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Qa View" })).toBeVisible();
  await expect(preview.locator("marimo-cell")).toHaveCount(0);

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
  replacedWorkspaceStreams.recovered();
});

test.describe("touch input", () => {
  test.use({ hasTouch: true });

  test("keeps view removal directly available without hover", async ({ page }) => {
    await addWorkspaceView(workspaceNotebookPath, "report");
    await page.goto(studioEntryUrl);
    await waitForPreview(page);
    await page.getByLabel("Switch view").tap();
    await page.getByLabel("Remove report view").tap();

    await expect(page.getByText(/authored source and published artifacts/)).toContainText("report");
    await page.getByRole("button", { name: "Cancel" }).tap();
    await expect(page.getByLabel("Remove report view")).toBeFocused();
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
