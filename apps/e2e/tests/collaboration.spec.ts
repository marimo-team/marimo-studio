import type { FrameLocator, Page } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.ts";
import { collaborativeNotebookPath } from "../scripts/paths.ts";
import {
  saveShortcut,
  selectAllShortcut,
  studioClientId,
  studioEditorSessionId,
} from "./authoring-test-support.ts";
import {
  captureProjectionRefresh,
  collaborativeDashboardHtmlPath,
  collaborativeStudioEntryUrl,
  dashboardHtmlPath,
  expect,
  expectSupersededRenewalConfig,
  labeledSlider,
  observeBrowserContext,
  readWorkspaceFile,
  recoverProjectionRefresh,
  recoverRequestAbort,
  studioEntryUrl,
  studioOrigin,
  studioServerToken,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeViewSource,
  writeWorkspaceFile,
} from "./fixture.ts";
import { startNotebookServer } from "./notebook-server.ts";

const holdDashboardSourceWrites = async (page: Page): Promise<() => Promise<void>> => {
  const sourceRoute = /\/_marimo-studio\/views\/dashboard\/source\/src\/index\.html(?:\?|$)/;
  let release!: () => void;
  let claimed = false;
  let finish!: () => void;
  const committed = new Promise<void>((resolve) => {
    release = resolve;
  });
  const finished = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const handler: Parameters<Page["route"]>[1] = async (route) => {
    if (route.request().method() !== "PUT" || claimed) {
      await route.fallback();
      return;
    }
    claimed = true;
    try {
      await committed;
      await route.continue();
    } finally {
      finish();
    }
  };
  await page.route(sourceRoute, handler);
  return async () => {
    await expect.poll(() => claimed, { timeout: 65_000 }).toBe(true);
    release();
    await finished;
    // Keep the pass-through route until the page closes: disabling interception
    // while publication starts source reads can leave a Chromium request paused.
  };
};

const expectSharedHeading = async (
  first: FrameLocator,
  second: FrameLocator,
  heading: string,
): Promise<void> => {
  await Promise.all([
    expect(first.getByRole("heading", { name: heading })).toBeVisible({ timeout: 65_000 }),
    expect(second.getByRole("heading", { name: heading })).toBeVisible({ timeout: 65_000 }),
  ]);
};

const readDashboardSource = async (page: Page): Promise<string> => {
  const response = await page.request.get(
    new URL("/_marimo-studio/views/dashboard/source/src/index.html?file=notebook.py", page.url())
      .href,
  );
  if (!response.ok()) {
    throw new Error(`Could not read dashboard source (${response.status()})`);
  }
  return response.text();
};

test("synchronizes one notebook while each tab selects its view", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const replacedEventStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin()).href,
    3,
  );
  const supersededRenewalConfig = expectSupersededRenewalConfig(browserDiagnostics, "dashboard");
  const notebook = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace(
      'if __name__ == "__main__":',
      `@app.cell
def query_value(query_params):
    query_value = query_params.get("tab-query", "initial")
    return (query_value,)


if __name__ == "__main__":`,
    ),
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report");
  await page.goto(`${studioEntryUrl}&tab-query=initial`);
  const firstPreview = await waitForPreview(page);
  const second = await page.context().newPage();
  try {
    await second.goto(`${studioEntryUrl}&tab-query=initial`);
    const secondPreview = await waitForPreview(second);
    const firstClient = await studioClientId(page);
    const secondClient = await studioClientId(second);
    const firstEditorSession = await studioEditorSessionId(page);
    const secondEditorSession = await studioEditorSessionId(second);
    const firstFrame = page.locator('iframe[data-preview-runtime-frame="server"]');
    const secondFrame = second.locator('iframe[data-preview-runtime-frame="server"]');
    const initialFirstPreviewSession = await firstFrame.getAttribute("data-session-id");
    const initialSecondPreviewSession = await secondFrame.getAttribute("data-session-id");
    expect(firstClient).not.toBe(secondClient);
    expect(firstEditorSession).toMatch(/^s_[\da-z]{6}$/);
    expect(secondEditorSession).toMatch(/^s_[\da-z]{6}$/);
    expect(firstEditorSession).not.toBe(secondEditorSession);
    expect(initialFirstPreviewSession).toMatch(/^s_[\da-z]{6}$/);
    expect(initialSecondPreviewSession).toMatch(/^s_[\da-z]{6}$/);
    expect(initialFirstPreviewSession).not.toBe(initialSecondPreviewSession);

    const token = await studioServerToken(page);
    const ambiguous = await page.request.patch(
      "/_marimo-studio/views/report/show?file=notebook.py",
      {
        data: { schema: 1, browser_client: null },
        headers: { "Marimo-Server-Token": token },
      },
    );
    expect(ambiguous.status()).toBe(409);
    expect(await ambiguous.json()).toMatchObject({ error: "browser-client-ambiguous" });

    const activate = async (view: string, client: string) =>
      page.request.patch(`/_marimo-studio/views/${view}/show?file=notebook.py`, {
        data: { schema: 1, browser_client: client },
        headers: { "Marimo-Server-Token": token },
      });
    const supersededDashboardConfig = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/config$/,
      count: 1,
    });
    expect((await activate("report", secondClient)).status()).toBe(200);
    await expect(second.getByLabel("Switch view")).toContainText("report");
    await expect(secondPreview.getByRole("heading", { name: "Report" })).toBeVisible();
    await expect(page.getByLabel("Switch view")).toContainText("dashboard");

    expect((await activate("dashboard", secondClient)).status()).toBe(200);
    await expect(second.getByLabel("Switch view")).toContainText("dashboard");
    await expect(
      secondPreview.getByRole("heading", { name: "Studio browser fixture" }),
    ).toBeVisible();
    const original = await readWorkspaceFile(dashboardHtmlPath);
    const published = original.replace("Studio browser fixture", "Published to both tabs").replace(
      "</main>",
      `<nav aria-label="Shared query">
          <a href="?tab-query=first">Use first query</a>
          <a href="?tab-query=second">Use second query</a>
        </nav><p>Shared query: <strong id="shared-query" mo-value="query_value"></strong></p></main>`,
    );
    const firstSharedRefresh = await captureProjectionRefresh(page, browserDiagnostics);
    const secondSharedRefresh = await captureProjectionRefresh(second, browserDiagnostics);
    await writeViewSource(page, "dashboard", "src/index.html", published);
    await expect(
      firstPreview.getByRole("heading", { name: "Published to both tabs" }),
    ).toBeVisible();
    await expect(
      secondPreview.getByRole("heading", { name: "Published to both tabs" }),
    ).toBeVisible();

    const secondMetric = secondPreview.locator('[mo-value="metric"]');
    await labeledSlider(firstPreview.locator('marimo-cell[name="controls"]'), /^Scale/).press(
      "End",
    );
    await expect(firstPreview.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(secondMetric).toHaveText("63");
    await labeledSlider(secondPreview.locator('marimo-cell[name="controls"]'), /^Scale/).press(
      "Home",
    );
    await expect(firstPreview.locator('[mo-value="metric"]')).toHaveText("21");
    await expect(secondMetric).toHaveText("21");
    const retriedQuery = browserDiagnostics.expectRequestAbort({
      origin: studioOrigin(),
      method: "POST",
      path: /^\/_marimo-studio\/query$/,
      count: 1,
      required: false,
    });
    await firstPreview.getByRole("link", { name: "Use first query" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("tab-query")).toBe("first");
    await expect.poll(() => new URL(second.url()).searchParams.get("tab-query")).toBe("first");
    await expect(firstPreview.locator("#shared-query")).toHaveText("first");
    await expect(secondPreview.locator("#shared-query")).toHaveText("first");
    await recoverRequestAbort(retriedQuery);
    await secondPreview.getByRole("link", { name: "Use second query" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("tab-query")).toBe("second");
    await expect.poll(() => new URL(second.url()).searchParams.get("tab-query")).toBe("second");
    await expect(firstPreview.locator("#shared-query")).toHaveText("second");
    await expect(secondPreview.locator("#shared-query")).toHaveText("second");
    await firstPreview.getByRole("link", { name: "Use first query" }).click();
    await expect.poll(() => new URL(page.url()).searchParams.get("tab-query")).toBe("first");
    await expect.poll(() => new URL(second.url()).searchParams.get("tab-query")).toBe("first");
    await expect(firstPreview.locator("#shared-query")).toHaveText("first");
    await expect(secondPreview.locator("#shared-query")).toHaveText("first");
    await recoverProjectionRefresh(firstSharedRefresh, page);
    await recoverProjectionRefresh(secondSharedRefresh, second);
    const firstPreviewSession = await firstFrame.getAttribute("data-session-id");
    const secondPreviewSession = await secondFrame.getAttribute("data-session-id");
    expect(firstPreviewSession).toMatch(/^s_[\da-z]{6}$/);
    expect(secondPreviewSession).toMatch(/^s_[\da-z]{6}$/);
    expect(firstPreviewSession).not.toBe(secondPreviewSession);

    const reloadedSession = page.waitForRequest(
      (request) =>
        new URL(request.url()).pathname.endsWith("/_marimo-studio/editor/api/usage") &&
        Boolean(request.headers()["marimo-session-id"]),
    );
    await page
      .locator('iframe[title="Marimo editor"]')
      .evaluate((editor: HTMLIFrameElement) => editor.contentWindow?.location.reload());
    expect((await reloadedSession).headers()["marimo-session-id"]).toBe(firstEditorSession);
    await expect(firstFrame).toHaveAttribute("data-session-id", firstPreviewSession ?? "");
    await expect(secondFrame).toHaveAttribute("data-session-id", secondPreviewSession ?? "");

    const secondRetirement = browserDiagnostics.expectPageRetirement(second);
    await second.close();
    secondRetirement.recovered();
    await expect
      .poll(async () => {
        const response = await page.request.patch(
          "/_marimo-studio/views/report/show?file=notebook.py",
          {
            data: { schema: 1, browser_client: null },
            headers: { "Marimo-Server-Token": token },
          },
        );
        return response.status();
      })
      .toBe(200);
    await expect(page.getByLabel("Switch view")).toContainText("report");
    await expect(firstPreview.getByRole("heading", { name: "Report" })).toBeVisible();
    await expect(
      firstPreview.getByRole("button", { name: "Select a target", exact: true }),
    ).toBeVisible();
    await waitForPreview(page);
    replacedEventStreams.recovered();
    await recoverRequestAbort(supersededDashboardConfig);
    supersededRenewalConfig.recovered();
  } finally {
    if (!second.isClosed()) {
      await second.close();
    }
  }
});

test("shares publication and recovery across two Studio sessions", async ({
  browser,
  browserDiagnostics,
  collaborativeWorkspace: _collaborativeWorkspace,
  page,
  studioCli,
}, testInfo) => {
  test.setTimeout(180_000);
  await studioCli.addCollaborativeView("report");
  const firstServer = startNotebookServer({
    command: "edit",
    target: collaborativeNotebookPath,
    endpoint: e2eNetwork.main.collaboration,
    authentication: ["--no-token"],
  });
  const secondOrigin = e2eNetwork.main.collaborationPeer.origin;
  const secondEntry = `${secondOrigin}/?file=notebook.py`;
  const secondServer = startNotebookServer({
    command: "edit",
    target: collaborativeNotebookPath,
    endpoint: e2eNetwork.main.collaborationPeer,
    authentication: ["--no-token"],
  });
  try {
    await Promise.all([
      firstServer.waitUntilReady(collaborativeStudioEntryUrl()),
      secondServer.waitUntilReady(secondEntry),
    ]);
    await page.goto(collaborativeStudioEntryUrl());
    const firstPreview = await waitForPreview(page);
    await page.getByLabel("Workspace options").click();
    await page.getByRole("button", { name: "Focus Source", exact: true }).click();
    await page.getByRole("tab", { name: "src/index.html" }).click();
    const firstEditor = page.getByLabel("src/index.html source");
    const secondContext = await browser.newContext({ baseURL: secondOrigin });
    const secondDiagnostics = observeBrowserContext(secondContext);
    const sourceConflicts = secondDiagnostics.expectResponse({
      status: 412,
      path: /\/_marimo-studio\/views\/dashboard\/source\/src\/index\.html$/,
      error: "source-conflict",
      count: 2,
      required: false,
    });
    const second = await secondContext.newPage();
    try {
      await second.goto(secondEntry);
      const secondPreview = await waitForPreview(second);
      await second.getByLabel("Workspace options").click();
      await second.getByRole("button", { name: "Focus Source", exact: true }).click();
      await second.getByRole("tab", { name: "src/index.html" }).click();
      const secondEditor = second.getByLabel("src/index.html source");
      await expect(secondEditor).toBeVisible();
      const supersededConfigReads = secondDiagnostics.expectActiveRequestAbort({
        origin: secondOrigin,
        method: "GET",
        path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/config$/,
        count: 2,
      });
      const abandonedSourceWrites = secondDiagnostics.expectRequestAbort({
        origin: secondOrigin,
        method: "PUT",
        path: /^\/_marimo-studio\/views\/dashboard\/source\/src\/index\.html$/,
        count: 1,
        status: 204,
      });
      const abandonedPrimarySourceWrites = browserDiagnostics.expectRequestAbort({
        origin: e2eNetwork.main.collaboration.origin,
        method: "PUT",
        path: /^\/_marimo-studio\/views\/dashboard\/source\/src\/index\.html$/,
        count: 2,
        status: 204,
      });
      const firstSession = await page
        .locator('iframe[data-preview-runtime-frame="server"]')
        .getAttribute("data-session-id");
      const secondSession = await second
        .locator('iframe[data-preview-runtime-frame="server"]')
        .getAttribute("data-session-id");
      expect(firstSession).toMatch(/^s_[\da-z]{6}$/);
      expect(secondSession).toMatch(/^s_[\da-z]{6}$/);
      expect(secondSession).not.toBe(firstSession);

      const original = await readDashboardSource(page);
      const firstSave = original.replace("Studio browser fixture", "Saved by first client");
      const discarded = original.replace("Studio browser fixture", "Discarded second edit");
      const releaseDiscardedSave = await holdDashboardSourceWrites(second);
      await secondEditor.click();
      await secondEditor.press(selectAllShortcut);
      await second.keyboard.insertText(discarded);
      await firstEditor.click();
      await firstEditor.press(selectAllShortcut);
      await page.keyboard.insertText(firstSave);
      await firstEditor.press(saveShortcut);
      await expect.poll(() => readDashboardSource(page)).toBe(firstSave);
      await releaseDiscardedSave();

      await expect(second.getByRole("alert")).toContainText("changed on disk");
      await second.getByRole("button", { name: "Use saved version" }).click();
      await expect(secondEditor).toContainText("Saved by first client");
      await expectSharedHeading(firstPreview, secondPreview, "Saved by first client");
      await Promise.all([waitForPreview(page), waitForPreview(second)]);

      const secondWins = firstSave.replace("Saved by first client", "Saved by second client");
      const competing = firstSave.replace("Saved by first client", "Competing first edit");
      const releaseSecondSave = await holdDashboardSourceWrites(second);
      await secondEditor.click();
      await secondEditor.press(selectAllShortcut);
      await second.keyboard.insertText(secondWins);
      await firstEditor.click();
      await firstEditor.press(selectAllShortcut);
      await page.keyboard.insertText(competing);
      await firstEditor.press(saveShortcut);
      await expect.poll(() => readDashboardSource(page)).toBe(competing);
      await releaseSecondSave();
      await expectSharedHeading(firstPreview, secondPreview, "Competing first edit");
      await Promise.all([waitForPreview(page), waitForPreview(second)]);

      await expect(second.getByRole("alert")).toContainText("changed on disk");
      await second.getByRole("button", { name: "Overwrite saved version with my edits" }).click();
      await expect.poll(() => readDashboardSource(page)).toBe(secondWins);

      await expectSharedHeading(firstPreview, secondPreview, "Saved by second client");
      await Promise.all([waitForPreview(page), waitForPreview(second)]);
      sourceConflicts.recovered();
      const invalid = secondWins.replace("</body>", "");
      await writeWorkspaceFile(collaborativeDashboardHtmlPath, invalid);
      await expect
        .poll(async () => {
          const response = await second.request.get(
            "/_marimo-studio/views/dashboard/project?file=notebook.py",
          );
          return (await response.json()).build?.phase;
        })
        .toBe("stale");
      await expectSharedHeading(firstPreview, secondPreview, "Saved by second client");

      const repaired = secondWins.replace("Saved by second client", "Repaired publication");
      await writeWorkspaceFile(collaborativeDashboardHtmlPath, repaired);
      await expect
        .poll(async () => {
          const response = await second.request.get(
            "/_marimo-studio/views/dashboard/project?file=notebook.py",
          );
          return (await response.json()).build?.phase;
        })
        .toBe("published");
      await expectSharedHeading(firstPreview, secondPreview, "Repaired publication");
      await Promise.all([waitForPreview(page), waitForPreview(second)]);
      await expect(firstEditor).toContainText("Repaired publication");
      await expect(secondEditor).toContainText("Repaired publication");
      await expect(
        page
          .getByRole("region", { name: "Source" })
          .getByRole("status", { name: "Source document status" }),
      ).toHaveText("Saved");
      await expect(
        second
          .getByRole("region", { name: "Source" })
          .getByRole("status", { name: "Source document status" }),
      ).toHaveText("Saved");
      await recoverRequestAbort(abandonedPrimarySourceWrites);
      await recoverRequestAbort(abandonedSourceWrites);
      await recoverRequestAbort(supersededConfigReads);
    } finally {
      await secondDiagnostics.close();
      expect.soft(secondDiagnostics.messages, "unexpected second-client diagnostics").toEqual([]);
      await secondContext.close();
    }

    const remainingPreview = await waitForPreview(page);
    await expect(remainingPreview.locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
    const widget = remainingPreview.getByRole("button", { name: /Widget count:/ });
    const before = await widget.textContent();
    await widget.click();
    await expect(widget).not.toHaveText(before ?? "");
  } finally {
    await page.close();
    await Promise.all([firstServer.close(), secondServer.close()]);
    if (testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach("first-collaboration-server", {
        body: Buffer.from(firstServer.output()),
        contentType: "text/plain",
      });
      await testInfo.attach("second-collaboration-server", {
        body: Buffer.from(secondServer.output()),
        contentType: "text/plain",
      });
    }
  }
});
