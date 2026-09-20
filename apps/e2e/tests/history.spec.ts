import { chromium, expect as playwrightExpect } from "@playwright/test";

import {
  dashboardHtmlPath,
  expect,
  labeledSlider,
  observeBrowserContext,
  presentationFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  restoreWorkspace,
  test,
  WASM_PREVIEW_TIMEOUT,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";
import { test as playwrightTest } from "./network-fixture.ts";
import { stopNotebookServer, waitForNotebookServer } from "./notebook-server.ts";
import { runServerToken, runServerUrl, startRunServer } from "./recovery-support.ts";

test("keeps the configured WebAssembly default implicit across wrapper reload", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(360_000);
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source
      .replace("# preserve_session = false", "# preserve_session = true")
      .replace('# runtime = "server"', '# runtime = "wasm"'),
  );
  const dashboard = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    dashboard.replace(
      "</main>",
      `<p>Region: <strong id="wasm-region" mo-value='query_params["region"]'></strong></p>
      </main>`,
    ),
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const waitForReady = async (timeout = 65_000) => {
    const deadline = Date.now() + timeout;
    const remaining = () => Math.max(1, deadline - Date.now());
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
      timeout: remaining(),
    });
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("42", {
      timeout: remaining(),
    });
  };
  const mountedRuntime = () =>
    rendered.locator("html").evaluate(() => globalThis.__MARIMO_MOUNT_CONFIG__.runtime);

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl()}/dashboard/?access_token=${runServerToken}&region=emea`,
    );
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}&region=emea`);
    await waitForReady(WASM_PREVIEW_TIMEOUT);
    expect(await mountedRuntime()).toBe("wasm");
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?region=emea`);
    await expect(rendered.locator("#wasm-region")).toHaveText("emea");

    const implicitReloadDocument = browserDiagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await page.reload();
    await waitForReady();
    expect(await mountedRuntime()).toBe("wasm");
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?region=emea`);
    await expect(rendered.locator("#wasm-region")).toHaveText("emea");
    await recoverRequestAbort(implicitReloadDocument);

    const historyDocument = browserDiagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await page.goto("about:blank");
    await page.goBack();
    await waitForReady();
    expect(await mountedRuntime()).toBe("wasm");
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?region=emea`);
    await expect(rendered.locator("#wasm-region")).toHaveText("emea");
    await recoverRequestAbort(historyDocument);

    await page.goto(`${runServerUrl()}/dashboard/?region=emea&runtime=wasm`);
    await waitForReady();
    expect(await mountedRuntime()).toBe("wasm");
    const explicitReloadDocument = browserDiagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await page.reload();
    await waitForReady();
    expect(await mountedRuntime()).toBe("wasm");
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?region=emea&runtime=wasm`);
    await expect(rendered.locator("#wasm-region")).toHaveText("emea");
    const scale = labeledSlider(rendered.locator('marimo-cell[name="controls"]'), /^Scale/);
    await scale.press("End");
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await recoverRequestAbort(explicitReloadDocument);
  } finally {
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});

test("keeps explicit WebAssembly authority through a pre-ready wrapper reload", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(210_000);
  const nativeSessions: string[] = [];
  const nativeSockets: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health") && url.searchParams.has("session_id")) {
      nativeSessions.push(url.href);
    }
  });
  page.on("websocket", (socket) => {
    if (new URL(socket.url()).pathname.endsWith("/ws")) {
      nativeSockets.push(socket.url());
    }
  });
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const target = `${runServerUrl()}/dashboard/?access_token=${runServerToken}&runtime=wasm`;

  try {
    await waitForNotebookServer(server, target);
    await page.goto(target);
    const startupUrl = new URL(page.url());
    expect(startupUrl.pathname).toBe("/dashboard/");
    expect(startupUrl.searchParams.get("runtime")).toBe("wasm");
    expect(startupUrl.searchParams.get("access_token")).toBeNull();
    expect(startupUrl.searchParams.get("marimo_studio_client")).toBeNull();
    expect(startupUrl.searchParams.get("marimo_studio_lifecycle")).toBeNull();
    await expect(rendered.locator("html")).toBeAttached();
    const initial = await rendered.locator("html").evaluate(() => ({
      readyState: document.readyState,
      runtime: globalThis.__MARIMO_MOUNT_CONFIG__.runtime,
      runtimeExplicit: globalThis.__MARIMO_MOUNT_CONFIG__.runtimeExplicit,
      state: document.documentElement.dataset.marimoStudioState,
    }));
    expect(initial).toMatchObject({
      readyState: "complete",
      runtime: "wasm",
      runtimeExplicit: true,
    });
    expect(initial.state).not.toBe("ready");

    const frameElement = await page.locator("iframe#marimo-studio-presentation").elementHandle();
    if (!frameElement) {
      throw new Error("The pre-ready presentation element is unavailable.");
    }
    const retiringFrame = await frameElement.contentFrame().finally(() => frameElement.dispose());
    if (!retiringFrame) {
      throw new Error("The pre-ready presentation frame is unavailable.");
    }
    const retirement = browserDiagnostics.expectFrameRetirement(retiringFrame);
    await page.reload();
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
      timeout: WASM_PREVIEW_TIMEOUT,
    });
    retirement.recovered();
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?runtime=wasm`);
    const mounted = await rendered.locator("html").evaluate(() => ({
      runtime: globalThis.__MARIMO_MOUNT_CONFIG__.runtime,
      runtimeExplicit: globalThis.__MARIMO_MOUNT_CONFIG__.runtimeExplicit,
    }));
    expect(mounted).toEqual({
      runtime: "wasm",
      runtimeExplicit: true,
    });
    expect(nativeSessions).toEqual([]);
    expect(nativeSockets).toEqual([]);
  } finally {
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});

playwrightTest("keeps the preserved wrapper nonblank across back-forward restoration", async () => {
  await restoreWorkspace();
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const executablePath = process.env.MARIMO_STUDIO_E2E_BROWSER_PATH;
  const launchOptions: Parameters<typeof chromium.launch>[0] = {
    headless: true,
    ignoreDefaultArgs: ["--disable-back-forward-cache"],
  };
  if (executablePath) {
    launchOptions.executablePath = executablePath;
  }
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext();
  const diagnostics = observeBrowserContext(context);
  const page = await context.newPage();
  const rendered = presentationFrame(page);

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl()}/dashboard/?access_token=${runServerToken}`,
    );
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await playwrightExpect(rendered.locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
    const scale = labeledSlider(rendered.locator('marimo-cell[name="controls"]'), /^Scale/);
    await scale.press("End");
    const widget = rendered.getByRole("button", { name: "Widget count: 7" });
    await widget.click();
    await playwrightExpect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await playwrightExpect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    const sessionId = await rendered
      .locator("html")
      .evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);

    const replacedDocument = diagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await page.goto("about:blank");
    await page.goBack();
    await playwrightExpect(rendered.locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );

    playwrightExpect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await playwrightExpect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await playwrightExpect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    await recoverRequestAbort(replacedDocument);
  } finally {
    await diagnostics.close();
    await context.close();
    await browser.close();
    await stopNotebookServer(server);
    await restoreWorkspace();
  }
  playwrightExpect(diagnostics.messages, "unexpected browser diagnostics").toEqual([]);
});

test("keeps direct view history hot and starts a fresh session for a new public query", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  const notebook = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace("# preserve_session = false", "# preserve_session = true"),
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report");
  const dashboard = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    dashboard.replace(
      "</main>",
      `<nav aria-label="Direct view navigation">
        <a href="../report/#details">Report</a>
        <a href="#details">Dashboard details</a>
        <a href="../report/?region=apac#details">APAC report</a>
      </nav>
      <section id="details">Dashboard details section</section>
      </main>`,
    ),
  );
  const reportPath = workspaceCreatedViewHtmlPath("report");
  await writeWorkspaceFile(
    reportPath,
    `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Report</title>
  </head>
  <body>
    <main id="app-shell">
      <h1>Report</h1>
      <p>Projected total: <strong mo-value="metric"></strong></p>
      <section id="details">Report details section</section>
    </main>
  </body>
</html>
`,
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const waitForReady = async () => {
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  };

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl()}/dashboard/?access_token=${runServerToken}&runtime=server`,
    );
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}&runtime=server`);
    await waitForReady();
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?runtime=server`);
    const scale = labeledSlider(rendered.locator('marimo-cell[name="controls"]'), /^Scale/);
    await scale.press("End");
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    const widget = rendered.getByRole("button", { name: "Widget count: 7" });
    await widget.click();
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    const sessionId = await rendered
      .locator("html")
      .evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);

    const dashboardFrameElement = await page
      .locator("iframe#marimo-studio-presentation")
      .elementHandle();
    const dashboardFrame = await dashboardFrameElement
      ?.contentFrame()
      .finally(() => dashboardFrameElement.dispose());
    if (!dashboardFrame) {
      throw new Error("The direct dashboard presentation frame is unavailable");
    }
    const dashboardProjectionRevision = await rendered
      .locator("html")
      .evaluate(() => globalThis.marimoStudio.identity().projectionRevision);
    const reportRefresh = browserDiagnostics.expectProjectionRefresh(
      dashboardFrame,
      dashboardProjectionRevision,
      "view-transition",
    );
    const replacedNestedDashboard = browserDiagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await rendered.getByRole("link", { name: "Report", exact: true }).click();
    await expect(page).toHaveURL(/\/report\/\?runtime=server#details$/);
    await waitForReady();
    await expect(rendered.getByRole("heading", { name: "Report" })).toBeVisible();
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    let reportProjectionRevision = await rendered
      .locator("html")
      .evaluate(() => globalThis.marimoStudio.identity().projectionRevision);
    expect(reportProjectionRevision).not.toBe(dashboardProjectionRevision);
    reportRefresh.seal();
    await expect
      .poll(
        async () => {
          reportProjectionRevision = await rendered
            .locator("html")
            .evaluate(() => globalThis.marimoStudio.identity().projectionRevision);
          return reportRefresh.ready(reportProjectionRevision);
        },
        { timeout: 65_000 },
      )
      .toBe(true);
    if (!reportRefresh.recovered(reportProjectionRevision)) {
      throw new Error("The report projection refresh changed while recovery was committing.");
    }
    reportRefresh.dispose();
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);

    await page.goBack();
    await expect(page).toHaveURL(/\/dashboard\/\?runtime=server$/);
    await waitForReady();
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

    await rendered.getByRole("link", { name: "Dashboard details" }).click();
    await expect(page).toHaveURL(/\/dashboard\/\?runtime=server#details$/);
    await waitForReady();
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/\/dashboard\/\?runtime=server$/);
    await waitForReady();

    await rendered.getByRole("link", { name: "APAC report" }).click();
    await expect(page).toHaveURL(/\/report\/\?region=apac&runtime=server#details$/);
    await waitForReady();
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).not.toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("42");
    await recoverRequestAbort(replacedNestedDashboard);
  } finally {
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});
