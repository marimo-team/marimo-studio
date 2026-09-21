import type { Request } from "@playwright/test";

import { projectionDiagnosticSchema } from "@marimo-studio/protocol/runtime-config";
import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { workspaceDirectory } from "../scripts/paths.ts";
import {
  readViewRevision,
  runCellShortcut,
  saveShortcut,
  selectAllShortcut,
  studioClientId,
  studioEditorSessionId,
} from "./authoring-test-support.ts";
import {
  selectWorkspaceMode,
  captureProjectionRefresh,
  dashboardCssPath,
  dashboardHtmlPath,
  editorFrame,
  editorSlider,
  expect,
  expectSupersededRenewalConfig,
  previewFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  recoverProjectionRefresh,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeDashboardSource,
  writeWorkspaceFile,
} from "./fixture.ts";

test("reuses a warm view artifact with current notebook changes", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await studioCli.addWorkspaceView(workspaceNotebookPath, "qa-view");
  const qaSourcePath = workspaceCreatedViewHtmlPath("qa-view");
  const qaSource = await readWorkspaceFile(qaSourcePath);
  await writeWorkspaceFile(
    qaSourcePath,
    qaSource.replace(
      "</main>",
      '  <p>Current metric: <strong id="qa-metric" mo-value="metric"></strong></p>\n    </main>',
    ),
  );
  const artifactRoot = resolve(workspaceDirectory, "__marimo__/studio/notebook/qa-view/.artifacts");
  const receiptPath = resolve(artifactRoot, "development.json");
  await rm(artifactRoot, { force: true, recursive: true });

  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    2,
  );
  await expect(preview.getByRole("heading", { name: "Studio browser fixture" })).toBeVisible();
  await expect
    .poll(() => readWorkspaceFile(receiptPath).catch(() => null), { timeout: 30_000 })
    .not.toBeNull();
  const warmedReceipt = await readWorkspaceFile(receiptPath);

  const metricRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  const metricCell = editorFrame(page).locator('.marimo-cell[data-cell-name="metric"]');
  const metricEditor = metricCell.getByRole("textbox");
  await metricEditor.click();
  await metricEditor.press(selectAllShortcut);
  await page.keyboard.insertText(
    'metric = scale.value * 22\nresponsive_value = "responsive" * 80\nmetric',
  );
  await metricCell.hover();
  await metricCell.locator('button[data-testid="run-button"]:not(:disabled)').click();
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("44");
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain("scale.value * 22");
  await recoverProjectionRefresh(metricRefresh, page);

  const abandonedHandoff = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin(),
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 1,
    status: 204,
  });
  await page.getByLabel("Switch view").click();
  await page.getByRole("button", { name: "qa-view", exact: true }).click();
  await expect(preview.getByRole("heading", { name: "Qa View" })).toBeVisible();
  await expect(preview.locator("#qa-metric")).toHaveText("44");
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  await expect(page.getByLabel("View build details, Up to date")).toBeVisible();

  expect(await readWorkspaceFile(receiptPath)).toBe(warmedReceipt);
  await recoverRequestAbort(abandonedHandoff);
  replacedWorkspaceStreams.recovered();
});

test("keeps browser and disk source edits in sync", async ({ browserDiagnostics, page }) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Focus Source", exact: true }).click();
  await page.getByRole("tab", { name: "src/index.html" }).click();
  const sourceStatus = page
    .getByRole("region", { name: "Source" })
    .getByRole("status", { name: "Source document status" });
  const retainedSummary = await preview.locator("#rich-summary-output").elementHandle();
  const retainedSummaryContent = await preview
    .locator("#rich-summary-output > *")
    .first()
    .elementHandle();
  expect(retainedSummary).not.toBeNull();
  expect(retainedSummaryContent).not.toBeNull();

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
  expect(
    await retainedSummary?.evaluate(
      (host) => host === document.querySelector("#rich-summary-output"),
    ),
  ).toBe(true);
  expect(
    await retainedSummaryContent?.evaluate(
      (content) => content === document.querySelector("#rich-summary-output > *"),
    ),
  ).toBe(true);
  await waitForPreview(page);
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(preview.locator("#rich-summary-output h3")).toHaveText("Current total: 42");
  await selectWorkspaceMode(page, "Notebook");
  await editorSlider(page).press("End");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const changed = source.replace("Studio browser fixture</h1>", "Edited in Studio</h1>");
  const replacedSourceWrite = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin(),
    method: "PUT",
    path: /^\/_marimo-studio\/views\/dashboard\/source\/src\/index\.html$/,
    count: 1,
    status: 204,
  });
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  const htmlEditor = page.getByLabel("src/index.html source");
  await htmlEditor.focus();
  await htmlEditor.press(selectAllShortcut);
  await page.keyboard.insertText(changed);
  await htmlEditor.press(saveShortcut);
  await expect.poll(() => readWorkspaceFile(dashboardHtmlPath)).toBe(changed);
  await expect(sourceStatus).toHaveText("Saved");
  await expect(preview.getByRole("heading", { name: "Edited in Studio" })).toBeVisible();
  await waitForPreview(page);
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");
  await expect(preview.locator("#rich-summary-output h3")).toHaveText("Current total: 63");
  await recoverRequestAbort(replacedSourceWrite);
});

test("keeps configured aliases attached to edited notebook cells", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const supersededRenewal = expectSupersededRenewalConfig(browserDiagnostics, "dashboard");
  await studioCli.bindWorkspaceCell("range-control", 1);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    source.replace('name="controls"', 'name="range-control"'),
  );

  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    1,
  );
  const currentRevision = async () => {
    const response = await page.request.get(
      "/_marimo-studio/views/dashboard/config?file=notebook.py&runtime=server",
    );
    expect(response.ok()).toBe(true);
    return readViewRevision(await response.text());
  };
  const initialRevision = await currentRevision();
  await expect(preview.getByText("Scale", { exact: true })).toBeVisible();
  const aliasRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  const editor = editorFrame(page);
  const controlCell = editor.getByRole("textbox").filter({ hasText: 'label="Scale"' });
  await expect(controlCell).toHaveCount(1);
  await controlCell.click();
  await controlCell.press(selectAllShortcut);
  await page.keyboard.insertText(`fail_outputs = mo.ui.switch(
    value=False,
    label="Fail projected outputs",
)
scale = mo.ui.slider(
    start=1,
    stop=3,
    value=2,
    show_value=True,
    label="Adjusted",
)
mo.vstack([scale, fail_outputs])`);
  await page.keyboard.press("Shift+Enter");

  await expect(preview.getByText("Adjusted", { exact: true })).toBeVisible();
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain('label="Adjusted"');
  await expect.poll(currentRevision).not.toBe(initialRevision);
  await waitForPreview(page);
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(preview.locator("#rich-summary-output h3")).toHaveText("Current total: 42");
  await recoverProjectionRefresh(aliasRefresh, page);
  expect(await studioCli.checkWorkspace()).toBe(true);
  supersededRenewal.recovered();
  replacedWorkspaceStream.recovered();
});

test("keeps view feedback current while cells are added, edited, moved, and deleted", async ({
  browserDiagnostics,
  page,
}) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    4,
  );
  const originalView = await readWorkspaceFile(dashboardHtmlPath);
  await selectWorkspaceMode(page, "Notebook");
  const editor = editorFrame(page);
  const metricCell = editor.locator('[data-cell-name="metric"]');
  await metricCell.hover();
  const createButtons = metricCell.getByTestId("create-cell-button").locator(":visible");
  await expect(createButtons).toHaveCount(2);
  const addedRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await createButtons.last().click();
  const addedCell = editor.locator('[data-cell-name="_"]').last();
  const addedEditor = addedCell.getByRole("textbox");
  await addedEditor.click();
  await expect(addedEditor).toBeFocused();
  await addedEditor.fill('user_note = "Added from notebook"\nuser_note');
  const addedCellId = await addedCell.getAttribute("data-cell-id");
  expect(addedCellId).not.toBeNull();
  await addedCell.hover();
  await addedCell.locator('button[data-testid="run-button"]:not(:disabled)').click();
  await expect(addedCell.locator("..")).toHaveAttribute("data-status", "idle");
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain("user_note =");
  await waitForPreview(page);
  await recoverProjectionRefresh(addedRefresh, page);

  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  const projectedView = originalView.replace(
    "</main>",
    '  <p id="user-note"><strong mo-value="user_note"></strong></p>\n    </main>',
  );
  const projectedSourceRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await writeDashboardSource(page, projectedView);
  await waitForPreview(page);
  const note = preview.locator("#user-note strong");
  await expect(note).toHaveAttribute("data-state", "ready");
  await expect(note).toHaveText("Added from notebook");
  await recoverProjectionRefresh(projectedSourceRefresh, page);

  await selectWorkspaceMode(page, "Notebook");
  const editedRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await addedEditor.click();
  await addedEditor.press(selectAllShortcut);
  const editedNoteSource = 'user_note = "Edited from notebook"\nuser_note';
  await page.keyboard.insertText(editedNoteSource);
  await addedCell.hover();
  await addedCell.locator('button[data-testid="run-button"]:not(:disabled)').click();
  await expect(addedCell.locator("..")).toHaveAttribute("data-status", "idle");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(note).toHaveText("Edited from notebook");
  await recoverProjectionRefresh(editedRefresh, page);

  await selectWorkspaceMode(page, "Notebook");
  const cellOrder = () =>
    editor
      .locator("[data-cell-id]")
      .evaluateAll(
        (cells, selectedId) =>
          cells.findIndex((cell) => cell.getAttribute("data-cell-id") === selectedId),
        addedCellId,
      );
  const beforeMove = await cellOrder();
  const movedRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await addedCell.hover();
  await addedCell.locator('button[data-testid="cell-actions-button"]').click();
  await editor.getByText("Move cell down", { exact: true }).click();
  await expect.poll(cellOrder).toBe(beforeMove + 1);
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(note).toHaveText("Edited from notebook");
  await recoverProjectionRefresh(movedRefresh, page);

  await selectWorkspaceMode(page, "Notebook");
  const deletedRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await addedCell.hover();
  await addedCell.locator('button[data-testid="cell-actions-button"]').click();
  await editor.getByText("Delete", { exact: true }).last().click();
  const confirmDelete = editor.getByRole("button", { name: "Delete", exact: true });
  if (await confirmDelete.isVisible()) {
    await confirmDelete.click();
  }
  await expect(addedCell).toHaveCount(0);
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).not.toContain("user_note =");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  const missingNoteMessage =
    "Notebook variable 'user_note' does not resolve in the notebook. " +
    "Name the notebook cell or define the variable, then update the view.";
  await expect(note).toHaveAttribute("data-state", "error");
  await expect(note).toHaveText("Unavailable");
  await expect(note).toHaveAccessibleName(missingNoteMessage);
  await expect(note).toHaveAttribute("title", missingNoteMessage);
  await expect(preview.locator('marimo-cell[name="controls"]')).toHaveAttribute(
    "data-state",
    "ready",
  );
  const missingNoteDiagnostic = (
    await preview.locator("html").evaluate(() => globalThis.marimoStudio.diagnostics())
  )
    .map((diagnostic) => projectionDiagnosticSchema.safeParse(diagnostic))
    .find(
      (diagnostic) =>
        diagnostic.success &&
        diagnostic.data.code === "projection-value-variable-not-found" &&
        diagnostic.data.projection === "value" &&
        diagnostic.data.target === "user_note",
    )?.data;
  expect(missingNoteDiagnostic).toMatchObject({
    code: "projection-value-variable-not-found",
    severity: "error",
    target: "user_note",
  });
  const widget = preview.getByRole("button", { name: /Widget count:/ });
  const widgetBefore = await widget.textContent();
  await widget.click();
  await expect(widget).not.toHaveText(widgetBefore ?? "");
  deletedRefresh.capture.terminalizeValues(["user_note"]);
  await recoverProjectionRefresh(deletedRefresh, page);

  const repairedSourceRefresh = await captureProjectionRefresh(page, browserDiagnostics);
  await writeDashboardSource(page, originalView);
  await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Studio browser fixture" })).toBeVisible();
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("42");
  await expect(preview.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  await expect
    .poll(() =>
      preview.locator("html").evaluate(() =>
        globalThis.marimoStudio
          .diagnostics()
          .filter((diagnostic) => "target" in diagnostic && diagnostic.target === "user_note")
          .map(({ code }) => code),
      ),
    )
    .toEqual([]);
  await recoverProjectionRefresh(repairedSourceRefresh, page);
  replacedWorkspaceStreams.recovered();
});

test("shows progress while an edited notebook cell runs", async ({
  browserDiagnostics,
  page,
}, testInfo) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeDashboardSource(
    page,
    source.replace(
      "</main>",
      '  <p>Slow value: <strong id="slow-value" mo-value="slow_metric"></strong></p>\n    </main>',
    ),
  );
  await waitForPreview(page);
  await expect(preview.locator("#slow-value")).toHaveText("7");
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    1,
  );
  const slowRefresh = await captureProjectionRefresh(page, browserDiagnostics);

  const cell = editorFrame(page).locator('[data-cell-name="slow_metric"]');
  const code = cell.getByRole("textbox");
  const runtimeTrigger = page.getByRole("status", { name: "View status" });
  const gate = testInfo.outputPath("pending-computation");
  await writeFile(gate, "pending");
  try {
    await code.fill(`from pathlib import Path as _Path
import time as _time
while _Path(${JSON.stringify(gate)}).exists():
    _time.sleep(0.01)
slow_metric = 8
slow_metric`);
    await code.press(runCellShortcut);
    await expect(cell.locator("..")).toHaveAttribute("data-status", /queued|running/);
    await expect(runtimeTrigger).toHaveAttribute("data-state", "loading");
    await expect(runtimeTrigger).toContainText("Updating preview");
  } finally {
    await rm(gate, { force: true });
  }
  await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
  await waitForPreview(page);
  await expect(preview.locator("#slow-value")).toHaveText("8");
  await expect.poll(() => readWorkspaceFile(workspaceNotebookPath)).toContain("slow_metric = 8");
  await recoverProjectionRefresh(slowRefresh, page);
  await expect(runtimeTrigger).toHaveAttribute("data-state", "ready");
  await expect(runtimeTrigger).toContainText("Live");
  replacedWorkspaceStream.recovered();
});

test("keeps Source tabs and the editor reachable at narrow widths", async ({ page }) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Focus Source", exact: true }).click();
  const tablist = page.getByRole("tablist", { name: "View source files" });
  const tabs = page.getByRole("tab");
  expect(await tabs.count()).toBeGreaterThan(3);
  const first = tabs.first();
  const last = tabs.last();

  await page.setViewportSize({ width: 320, height: 720 });
  await last.focus();
  await last.press("Home");
  await expect(first).toHaveAttribute("aria-selected", "true");
  await first.press("End");
  await expect(last).toBeFocused();
  await expect(last).toHaveAttribute("aria-selected", "true");
  const tabMetrics = await tablist.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollLeft: element.scrollLeft,
    scrollWidth: element.scrollWidth,
  }));
  expect(tabMetrics.scrollWidth).toBeGreaterThan(tabMetrics.clientWidth);
  expect(tabMetrics.scrollLeft).toBeGreaterThan(0);
  const activeBounds = await last.evaluate((element) => {
    const tab = element.getBoundingClientRect();
    const list = element.closest('[role="tablist"]')?.getBoundingClientRect();
    return {
      listLeft: list?.left ?? 0,
      listRight: list?.right ?? 0,
      tabLeft: tab.left,
      tabRight: tab.right,
    };
  });
  expect(activeBounds.tabLeft).toBeGreaterThanOrEqual(activeBounds.listLeft - 1);
  expect(activeBounds.tabRight).toBeLessThanOrEqual(activeBounds.listRight + 1);
  const path = await last.getAttribute("aria-label");
  expect(path).not.toBeNull();
  const editor = page.getByLabel(`${path} source`);
  await expect(editor).toBeVisible();
  await expect(editor).toHaveAttribute("aria-readonly", "false");
  await last.press("Tab");
  await expect(editor).toBeFocused();
});

test("shows an agent-requested page and records its rendered revision", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await studioCli.addWorkspaceView(workspaceNotebookPath, "qa-view");
  const sessionRequest = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname.endsWith("/_marimo-studio/editor/api/usage") &&
      Boolean(request.headers()["marimo-session-id"]),
  );
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await expect(
    previewFrame(page).getByRole("heading", { name: "Studio browser fixture" }),
  ).toBeVisible();

  const sessionId = (await sessionRequest).headers()["marimo-session-id"];
  const clientId = await studioClientId(page);
  const replacedEventStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    1,
  );
  const activated = await studioCli.activateWorkspaceView("qa-view", clientId);
  expect(activated).toMatchObject({
    client_id: clientId,
    generation: expect.any(Number),
    session_id: sessionId,
    view: "qa-view",
  });
  await expect(page.locator(activated.frame_selector)).toHaveCount(1);
  await expect(page.locator(activated.frame_selector)).toHaveJSProperty(
    "src",
    activated.preview_url,
  );
  await expect(page.frameLocator(activated.frame_selector).locator("html")).toHaveAttribute(
    "data-marimo-studio-state",
    "ready",
  );
  await expect(
    page.frameLocator(activated.frame_selector).getByRole("heading", { name: "Qa View" }),
  ).toBeVisible();
  await expect(page.getByLabel("Switch view")).toContainText("qa-view");
  await expect(previewFrame(page).getByRole("heading", { name: "Qa View" })).toBeVisible();
  replacedEventStream.recovered();
  const refreshed = await studioCli.activateWorkspaceView("qa-view", clientId);
  expect(refreshed.preview_url).not.toBe(activated.preview_url);
  await expect(page.locator(refreshed.frame_selector)).toHaveCount(1);
  await expect(page.locator(refreshed.frame_selector)).toHaveJSProperty(
    "src",
    refreshed.preview_url,
  );
  const refreshedElement = await page.locator(refreshed.frame_selector).elementHandle();
  const refreshedDocument = await refreshedElement?.contentFrame();
  if (!refreshedDocument) throw new Error("The selected preview has no browser frame");
  const expectedLifecycle = new URL(refreshed.preview_url).searchParams.get(
    "marimo_studio_lifecycle",
  );
  expect(expectedLifecycle).toBeTruthy();
  await refreshedDocument.waitForURL(
    (url) => url.searchParams.get("marimo_studio_lifecycle") === expectedLifecycle,
  );
  await expect(page.frameLocator(refreshed.frame_selector).locator("html")).toHaveAttribute(
    "data-marimo-studio-state",
    "ready",
  );
  await expect(
    page.frameLocator(refreshed.frame_selector).getByRole("heading", { name: "Qa View" }),
  ).toBeVisible();
  const active = page.frameLocator(refreshed.frame_selector);
  const mountedRevision = await active.locator("html").getAttribute("data-marimo-studio-revision");
  expect(mountedRevision).toBeTruthy();
  const targets = ["controls", "metric", "slow_metric", "counter_widget"];
  for (const name of targets) {
    const host = active.locator(`marimo-cell[name="${name}"]`);
    await expect(host).toHaveAttribute("data-state", "ready");
    await expect(host).not.toHaveAttribute("aria-busy", "true");
  }

  const direct = await page.context().newPage();
  try {
    const url = await studioCli.previewWorkspaceView("qa-view", "server", true);
    const checkpoint = new URL(url).searchParams.get("marimo_studio_revision");
    expect(checkpoint).toBe(mountedRevision);
    const response = await direct.goto(url);
    expect(response?.ok()).toBe(true);
    expect(response?.headers()["marimo-studio-revision"]).toBe(checkpoint);
    await expect(direct.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(direct.locator("html")).toHaveAttribute(
      "data-marimo-studio-revision",
      mountedRevision!,
    );
    await expect(direct.getByRole("heading", { name: "Qa View" })).toBeVisible();
    await expect(direct.locator("iframe#marimo-studio-presentation")).toHaveCount(0);
  } finally {
    await direct.close();
  }
});

test("keeps a slow activation open until the selected view is acknowledged", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  test.setTimeout(60_000);
  const replacedEventStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    1,
  );
  const timedOutAcknowledgement = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin(),
    method: "POST",
    path: /^\/_marimo-studio\/activations\/\d+\/ack$/,
    count: 1,
  });
  await studioCli.addWorkspaceView(workspaceNotebookPath, "slow-activation");
  let releaseAcknowledgement = () => {};
  let retryStarted = () => {};
  const release = new Promise<void>((resolveRelease) => {
    releaseAcknowledgement = resolveRelease;
  });
  const retried = new Promise<void>((resolveStarted) => {
    retryStarted = resolveStarted;
  });
  let attempts = 0;
  await page.route(/\/_marimo-studio\/activations\/\d+\/ack(?:\?|$)/, async (route) => {
    attempts += 1;
    if (attempts === 2) {
      retryStarted();
    }
    await release;
    await route.continue().catch(() => undefined);
  });

  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const clientId = await studioClientId(page);
  const activation = studioCli.activateWorkspaceView("slow-activation", clientId);
  let activationSettled = false;
  void activation.then(
    () => {
      activationSettled = true;
    },
    () => {
      activationSettled = true;
    },
  );
  try {
    await retried;
    await expect(page.getByLabel("Switch view")).toContainText("slow-activation");
    await expect(
      preview.getByRole("heading", { name: "Slow Activation", exact: true }),
    ).toBeVisible();
    expect(activationSettled).toBe(false);
  } finally {
    releaseAcknowledgement();
  }
  await expect(activation).resolves.toMatchObject({
    client_id: clientId,
    generation: expect.any(Number),
    view: "slow-activation",
  });
  await expect(page.getByLabel("Switch view")).toContainText("slow-activation");
  await expect(
    preview.getByRole("heading", { name: "Slow Activation", exact: true }),
  ).toBeVisible();
  await recoverRequestAbort(timedOutAcknowledgement);
  replacedEventStream.recovered();
});

test("retains mounted browser evidence after the native editor reconnects", async ({ page }) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const sessionId = await studioEditorSessionId(page);
  const root = preview.locator("html");
  await expect(root).toHaveAttribute("data-marimo-studio-state", "ready");
  const revision = await root.getAttribute("data-marimo-studio-revision");
  expect(revision).toBeTruthy();
  await editorSlider(page).press("End");
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");
  const reloadedSession = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname.endsWith("/_marimo-studio/editor/api/usage") &&
      Boolean(request.headers()["marimo-session-id"]),
  );
  await page
    .locator('iframe[title="Marimo editor"]')
    .evaluate((editor: HTMLIFrameElement) => editor.contentWindow?.location.reload());
  expect((await reloadedSession).headers()["marimo-session-id"]).toBe(sessionId);
  await waitForPreview(page);
  await expect(root).toHaveAttribute("data-marimo-studio-state", "ready");
  await expect(root).toHaveAttribute("data-marimo-studio-revision", revision!);
  await editorSlider(page).press("End");
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("63");
  await editorSlider(page).press("Home");
  await expect(preview.locator('[mo-value="metric"]')).toHaveText("21");
});

test("advances a live preview while an exact checkpoint stays visibly stale", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await studioCli.addWorkspaceView(workspaceNotebookPath, "checkpoint-view");
  const sourcePath = workspaceCreatedViewHtmlPath("checkpoint-view");
  const source =
    "<!doctype html><html><head><title>Checkpoint</title></head><body><main id='app-shell'><h1>Checkpoint one</h1></main></body></html>";
  await writeWorkspaceFile(sourcePath, source);
  await studioCli.buildWorkspaceView("checkpoint-view", workspaceNotebookPath);
  await page.goto(studioEntryUrl);
  await waitForPreview(page);

  const live = await page.context().newPage();
  const exact = await page.context().newPage();
  const stopOutputTransitions: (() => void)[] = [];
  try {
    const liveUrl = await studioCli.previewWorkspaceView("checkpoint-view", "server");
    const exactUrl = await studioCli.previewWorkspaceView("checkpoint-view", "server", true);
    const checkpoint = new URL(exactUrl).searchParams.get("marimo_studio_revision");
    expect(checkpoint).toBeTruthy();
    const liveEvents = live.waitForRequest((request) =>
      new URL(request.url()).pathname.endsWith("/_marimo-studio/views/checkpoint-view/dev/events"),
    );
    const initialOutputs = [live, exact].map((target) =>
      target.waitForRequest(
        (request) =>
          request.method() === "POST" &&
          request.frame() === target.mainFrame() &&
          new URL(request.url()).pathname.endsWith("/_marimo-studio/views/checkpoint-view/outputs"),
      ),
    );
    await live.goto(liveUrl);
    await exact.goto(exactUrl);
    for (const target of [live, exact]) {
      await expect(target.getByRole("heading", { name: "Checkpoint one" })).toBeVisible();
      await expect(target.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
      await expect(target.locator("html")).toHaveAttribute(
        "data-marimo-studio-revision",
        checkpoint!,
      );
    }

    const exactPath = new RegExp(`^${RegExp.escape(new URL(exact.url()).pathname)}$`);
    const liveStream = await liveEvents;
    const retiredLiveStream = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: new RegExp(`^${RegExp.escape(new URL(liveStream.url()).pathname)}$`),
      status: 200,
    });
    const outputRequests = await Promise.all(initialOutputs);
    const recoverStaleOutputs: (() => void)[] = [];
    for (const [index, target] of [live, exact].entries()) {
      const initial = new URL(outputRequests[index]!.url());
      const onRequest = (request: Request): void => {
        const url = new URL(request.url());
        if (
          request.method() !== "POST" ||
          request.frame() !== target.mainFrame() ||
          url.origin !== initial.origin ||
          url.pathname !== initial.pathname
        )
          return;
        const response = browserDiagnostics.expectResponse({
          status: 409,
          path: new RegExp(`^${RegExp.escape(initial.pathname)}$`),
          required: false,
        });
        recoverStaleOutputs.push(() => response.recovered());
      };
      target.on("request", onRequest);
      stopOutputTransitions.push(() => target.off("request", onRequest));
    }
    const staleRefresh = browserDiagnostics.expectResponse({
      status: 409,
      path: exactPath,
      error: "presentation-revision-mismatch",
    });
    const staleConsole = browserDiagnostics.expectConsole({
      type: "error",
      text: /marimo-studio presentation refresh error.*exact preview is stale/i,
    });
    await writeWorkspaceFile(sourcePath, source.replace("Checkpoint one", "Checkpoint two"));
    await expect(live.getByRole("heading", { name: "Checkpoint two" })).toBeVisible({
      timeout: 65_000,
    });
    await expect(live.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(live.locator("html")).not.toHaveAttribute(
      "data-marimo-studio-revision",
      checkpoint!,
    );
    await expect(exact.getByRole("heading", { name: "Checkpoint one" })).toBeVisible();
    await expect(exact.locator("html")).toHaveAttribute("data-marimo-studio-state", "error");
    await expect(exact.locator("html")).toHaveAttribute("data-marimo-studio-revision", checkpoint!);
    await expect(exact.getByRole("alert")).toContainText("This exact preview is stale");
    await recoverRequestAbort(retiredLiveStream);
    staleRefresh.recovered();
    staleConsole.recovered();

    const staleNavigation = browserDiagnostics.expectResponse({
      status: 409,
      path: exactPath,
    });
    const response = await exact.reload();
    expect(response?.status()).toBe(409);
    await expect(exact.getByText(/This exact preview is stale/)).toBeVisible();
    await expect(exact.locator("html")).toHaveAttribute("data-marimo-studio-state", "error");
    await expect(exact.locator("html")).not.toHaveAttribute("data-marimo-studio-revision");
    staleNavigation.recovered();
    stopOutputTransitions.forEach((stop) => stop());

    const refreshedUrl = await studioCli.previewWorkspaceView("checkpoint-view", "server", true);
    await exact.goto(refreshedUrl);
    await expect(exact.getByRole("heading", { name: "Checkpoint two" })).toBeVisible();
    await expect(exact.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(exact.locator("html")).toHaveAttribute(
      "data-marimo-studio-revision",
      new URL(refreshedUrl).searchParams.get("marimo_studio_revision")!,
    );
    recoverStaleOutputs.forEach((recover) => recover());
  } finally {
    stopOutputTransitions.forEach((stop) => stop());
    await live.close();
    await exact.close();
  }
});
