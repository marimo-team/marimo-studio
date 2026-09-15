import { valueReadResponseSchema } from "@marimo-studio/protocol/value-read";

import { e2eNetwork } from "../scripts/network.mjs";
import { collaborativeWorkspaceDirectory } from "../scripts/paths.mjs";
import { studioClientId } from "./authoring-test-support.ts";
import {
  selectWorkspaceMode,
  collaborativeCreatedViewHtmlPath,
  expect,
  labeledSlider,
  observeBrowserContext,
  readWorkspaceFile,
  recoverRequestAbort,
  studioEntryUrl,
  studioOrigin,
  studioServerToken,
  test,
  waitForPreview,
  waitForViewPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";
import {
  startNotebookServer,
  stopNotebookServer,
  waitForNotebookServer,
} from "./notebook-server.ts";

declare global {
  var __studioPreviewWindowMarker: string | undefined;
}

const valueReportSource = (heading: string): string => `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${heading}</title>
  </head>
  <body>
    <main id="app-shell">
      <h2>${heading}</h2>
      <marimo-cell name="controls"></marimo-cell>
      <strong mo-value="slow_metric"></strong>
    </main>
  </body>
</html>
`;

test("cancels one client's held old-view request without changing the peer view", async ({
  browser,
  browserDiagnostics,
  collaborativeWorkspace: _collaborativeWorkspace,
  page,
  studioCli,
}) => {
  await studioCli.addCollaborativeView("report");
  const reportPath = collaborativeCreatedViewHtmlPath("report");
  const reportSource = await readWorkspaceFile(reportPath);
  await writeWorkspaceFile(
    reportPath,
    reportSource.replace(
      "</main>",
      '<marimo-cell name="controls"></marimo-cell><p>Report metric: <strong mo-value="metric"></strong></p></main>',
    ),
  );
  const origin = e2eNetwork.main.collaborationPeer.origin;
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", origin).href,
    1,
  );
  const entry = `${origin}/?file=notebook.py`;
  const firstServer = startNotebookServer({
    command: "edit",
    target: collaborativeWorkspaceDirectory,
    port: e2eNetwork.main.collaborationPeer.port,
    authentication: ["--no-token"],
  });
  const secondOrigin = e2eNetwork.main.collaboration.origin;
  const secondEntry = `${secondOrigin}/?file=notebook.py`;
  const secondServer = startNotebookServer({
    command: "edit",
    target: collaborativeWorkspaceDirectory,
    port: e2eNetwork.main.collaboration.port,
    authentication: ["--no-token"],
  });
  const secondContext = await browser.newContext({ baseURL: secondOrigin });
  const secondDiagnostics = observeBrowserContext(secondContext);
  const second = await secondContext.newPage();
  try {
    await Promise.all([
      waitForNotebookServer(firstServer, entry),
      waitForNotebookServer(secondServer, secondEntry),
    ]);
    await page.goto(entry);
    await second.goto(secondEntry);
    const firstPreview = await waitForPreview(page);
    const secondPreview = await waitForPreview(second);
    const firstClient = await studioClientId(page);
    const firstSession = await page
      .locator('iframe[data-preview-runtime-frame="server"]')
      .getAttribute("data-session-id");
    const secondSession = await second
      .locator('iframe[data-preview-runtime-frame="server"]')
      .getAttribute("data-session-id");
    expect(firstSession).not.toBe(secondSession);
    const firstMetric = firstPreview.locator('[mo-value="metric"]');
    const secondMetric = secondPreview.locator('[mo-value="metric"]');
    const peerMetric = await secondMetric.textContent();
    await expect(firstMetric).toHaveText(peerMetric ?? "");
    await secondPreview.locator("html").evaluate((root) => {
      root.dataset.lateResponsePeer = "retained";
    });

    let release!: () => void;
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    let intercepted!: () => void;
    const delayed = new Promise<void>((resolve) => {
      intercepted = resolve;
    });
    let completed!: () => void;
    const requestCompleted = new Promise<void>((resolve) => {
      completed = resolve;
    });
    let lateMetric: unknown;
    let held = false;
    let heldRequestAbort: ReturnType<typeof browserDiagnostics.expectHeldRequestAbort> | undefined;
    await page.route(/\/_marimo-studio\/views\/dashboard\/values(?:\?|$)/, async (route) => {
      const request = route.request();
      if (held || request.method() !== "POST") {
        await route.continue();
        return;
      }
      held = true;
      const response = await route.fetch();
      const value = valueReadResponseSchema.parse(await response.json()).values.metric;
      if (value?.codec !== "json-v1") {
        throw new Error("Expected the metric value to use JSON encoding.");
      }
      lateMetric = value.value;
      heldRequestAbort = browserDiagnostics.expectHeldRequestAbort(request, requestCompleted);
      intercepted();
      await released;
      try {
        await route.fulfill({ response });
      } finally {
        completed();
      }
    });

    const firstScale = labeledSlider(
      firstPreview.locator('marimo-cell[name="controls"]'),
      /^Scale/,
    );
    await firstScale.press("End");
    await delayed;
    if (heldRequestAbort === undefined) {
      throw new Error("The held dashboard value request was not captured.");
    }
    const activation = await page.request.patch(
      `${origin}/_marimo-studio/views/report/show?file=notebook.py`,
      {
        data: { schema: 1, browser_client: firstClient },
        headers: { "Marimo-Server-Token": await studioServerToken(page) },
      },
    );
    expect(activation.status()).toBe(200);
    await expect(page.getByLabel("Switch view")).toContainText("report");
    await expect(firstPreview.getByRole("heading", { name: "Report" })).toBeVisible();
    const reportMetric = firstPreview.locator('[mo-value="metric"]');
    await expect(reportMetric).toHaveText(String(lateMetric));
    const reportScale = labeledSlider(
      firstPreview.locator('marimo-cell[name="controls"]'),
      /^Scale/,
    );
    await reportScale.press("Home");
    await expect(reportMetric).toHaveText("21");
    release();
    await requestCompleted;
    await heldRequestAbort.requestFailed();

    await expect(firstPreview.getByRole("heading", { name: "Report" })).toBeVisible();
    await expect(reportMetric).toHaveText("21");
    await expect(second.getByLabel("Switch view")).toContainText("dashboard");
    expect(String(lateMetric)).not.toBe(peerMetric);
    await expect(secondMetric).toHaveText(peerMetric ?? "");
    await expect(secondPreview.locator("html")).toHaveAttribute(
      "data-late-response-peer",
      "retained",
    );
    heldRequestAbort.recovered();
    replacedWorkspaceStream.recovered();
  } finally {
    await secondDiagnostics.close();
    expect(secondDiagnostics.messages, "unexpected second-client diagnostics").toEqual([]);
    await secondContext.close();
    await page.close();
    await Promise.all([stopNotebookServer(firstServer), stopNotebookServer(secondServer)]);
  }
});

test("cancels a held old-view request without changing current or cached view state", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    5,
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "slow-report");
  await studioCli.addWorkspaceView(workspaceNotebookPath, "next-report");
  await writeWorkspaceFile(
    workspaceCreatedViewHtmlPath("slow-report"),
    valueReportSource("Slow kernel report"),
  );
  await writeWorkspaceFile(
    workspaceCreatedViewHtmlPath("next-report"),
    valueReportSource("Next kernel report"),
  );
  await studioCli.buildWorkspaceView("slow-report");
  await studioCli.buildWorkspaceView("next-report");
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const completedHandoffs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/,
    count: 5,
    required: false,
    status: 204,
  });
  const supersededValueReads = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/(?:slow-report|next-report)\/values$/,
    errorText: "net::ERR_ABORTED",
    count: 5,
    required: false,
  });
  const selectView = async (view: string, heading: string): Promise<void> => {
    const committed = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        response.status() === 204 &&
        response.request().method() === "POST" &&
        /^\/_marimo-studio\/active-view-handoffs\/[^/]+$/.test(url.pathname)
      );
    });
    await page.getByLabel("Switch view").click();
    await page.getByRole("button", { name: view, exact: true }).click();
    await committed;
    await expect(page.getByLabel("Switch view")).toContainText(view);
    const selected = await waitForViewPreview(page, view);
    await expect(selected.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  };
  await selectView("slow-report", "Slow kernel report");
  const preview = await waitForPreview(page);
  await selectView("next-report", "Next kernel report");
  await selectView("slow-report", "Slow kernel report");
  await selectWorkspaceMode(page, "Preview");
  await preview.locator("html").evaluate(() => {
    globalThis.__studioPreviewWindowMarker = "slow-report-window";
  });
  await expect(preview.locator('[mo-value="slow_metric"]')).toHaveText("7");
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  let intercepted!: () => void;
  const delayed = new Promise<void>((resolve) => {
    intercepted = resolve;
  });
  let completed!: () => void;
  const requestCompleted = new Promise<void>((resolve) => {
    completed = resolve;
  });
  let held = false;
  let heldRequestAbort: ReturnType<typeof browserDiagnostics.expectHeldRequestAbort> | undefined;
  await page.route(/\/_marimo-studio\/views\/slow-report\/values(?:\?|$)/, async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const value = valueReadResponseSchema.parse(await response.json()).values.slow_metric;
    if (held || value?.codec !== "json-v1" || value.value !== 21) {
      await route.fulfill({ response });
      return;
    }
    held = true;
    heldRequestAbort = browserDiagnostics.expectHeldRequestAbort(request, requestCompleted);
    intercepted();
    await released;
    try {
      await route.fulfill({ response });
    } finally {
      completed();
    }
  });
  const slowScale = labeledSlider(preview.locator('marimo-cell[name="controls"]'), /^Slow scale/);
  await slowScale.press("End");
  await expect(slowScale).toHaveAttribute("aria-valuenow", "3");
  await delayed;
  if (heldRequestAbort === undefined) {
    throw new Error("The held live value request was not captured.");
  }

  await selectView("next-report", "Next kernel report");
  await expect(page.getByRole("button", { name: "Show view beside notebook" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  const currentScale = labeledSlider(
    preview.locator('marimo-cell[name="controls"]'),
    /^Slow scale/,
  );
  await currentScale.press("Home");
  await expect(preview.locator('[mo-value="slow_metric"]')).toHaveText("7");
  release();
  await requestCompleted;
  await heldRequestAbort.requestFailed();

  await expect
    .poll(() => preview.locator("html").evaluate(() => globalThis.__studioPreviewWindowMarker))
    .toBeUndefined();
  await expect(
    preview.getByRole("heading", { name: "Next kernel report", exact: true }),
  ).toBeVisible();
  await expect(preview.locator('[mo-value="slow_metric"]')).toHaveText("7");
  await selectView("slow-report", "Slow kernel report");
  await expect
    .poll(() => preview.locator("html").evaluate(() => globalThis.__studioPreviewWindowMarker))
    .toBe("slow-report-window");
  await expect(preview.locator('[mo-value="slow_metric"]')).toHaveText("7");
  heldRequestAbort.recovered();
  await recoverRequestAbort(completedHandoffs);
  supersededValueReads.recovered();
  replacedWorkspaceStreams.recovered();
});
