import type { Page } from "@playwright/test";

import { DOCUMENT_LIFECYCLE_QUERY_PARAM } from "@marimo-studio/protocol/query";

import { studioEditorSessionId } from "./authoring-test-support.ts";
import {
  type BrowserDiagnostics,
  dashboardHtmlPath,
  editorFrame,
  editorSlider,
  expect,
  expectPreviewInteractive,
  presentationFrame,
  previewFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  staticExportUrl,
  studioEntryUrl,
  studioOrigin,
  studioServerToken,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
  writeDashboardSource,
} from "./fixture.ts";

const activateServerPreview = async (
  page: Page,
  diagnostics: BrowserDiagnostics,
): Promise<void> => {
  // Control discovery can start while the runtime menu is open.
  const controls = diagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/views\/dashboard\/controls$/,
    count: 1,
    required: false,
  });
  await page.getByLabel("Browser preview runtime").click();
  await page.getByRole("button", { name: /Python/ }).click();
  await expectPreviewInteractive(page, "server");
  await recoverRequestAbort(controls);
};

test.describe.configure({ timeout: 150_000 });
test.use({ services: ["studio", "static"] });

const waitForPresentationRuntime = async (root: ReturnType<typeof presentationFrame>) => {
  await expect
    .poll(() =>
      root
        .locator("html")
        .evaluate(async () => {
          if (!globalThis.marimoStudio) return false;
          return Promise.race([
            globalThis.marimoStudio.ready().then(() => true),
            new Promise<false>((resolve) => setTimeout(() => resolve(false), 500)),
          ]);
        })
        .catch(() => false),
    )
    .toBe(true);
};

test("starts the notebook automatically and initializes WebAssembly on demand", async ({
  page,
}) => {
  test.setTimeout(210_000);
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);

  await expect(preview.locator('strong[mo-value="metric"]')).toHaveText("42");
  await expect(page.getByLabel("Python preview runtime")).toContainText("Live");
  for (const surface of ["Notebook", "Preview"]) {
    await expect(page.getByRole("region", { name: surface })).toBeVisible();
  }
  const wasmFrame = page.locator('iframe[data-preview-runtime-frame="wasm"]');

  await expect(wasmFrame).toHaveAttribute("src", "about:blank");
  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  await expectPreviewInteractive(page, "wasm");

  await expect(wasm.locator('strong[mo-value="metric"]')).toHaveText("42");
});

test("mounts the Copilot editor extension only while GitHub completion is enabled", async ({
  browserDiagnostics,
  page,
}) => {
  const closedCopilotTransport = browserDiagnostics.expectConsole({
    type: "warning",
    text: /^WebSocket transport connection closed Error: WebSocket connection to ws:\/\/[^/]+\/lsp\/copilot closed/,
    count: 2,
    required: false,
  });
  const replacedWorkspaceStreams = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", studioOrigin).href,
    2,
  );
  const loadSession = async (navigate: () => Promise<void>) => {
    const sessionRequest = page.waitForRequest(
      (request) =>
        new URL(request.url()).pathname.endsWith("/_marimo-studio/editor/api/usage") &&
        Boolean(request.headers()["marimo-session-id"]),
    );
    await navigate();
    await waitForPreview(page);
    return (await sessionRequest).headers()["marimo-session-id"];
  };
  let sessionId = await loadSession(async () => {
    await page.goto(studioEntryUrl);
  });
  const editor = editorFrame(page);
  const copilotStatus = editor.locator('[data-testid="footer-copilot-status"]');
  const saveCopilot = async (copilot: false | "github", targetSessionId = sessionId) => {
    const response = await page.request.post("/_marimo-studio/editor/api/kernel/save_user_config", {
      data: { config: { completion: { copilot } } },
      headers: {
        "Marimo-Server-Token": await studioServerToken(page),
        "Marimo-Session-Id": targetSessionId,
        "x-runtime-url": new URL("/_marimo-studio/editor/", page.url()).href,
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
  };

  let restoreCopilot = false;
  try {
    await expect(copilotStatus).toHaveCount(0);
    await saveCopilot("github");
    restoreCopilot = true;
    sessionId = await loadSession(async () => {
      await page.reload();
    });
    await expect(copilotStatus).toBeVisible();
    await saveCopilot(false);
    restoreCopilot = false;
    await loadSession(async () => {
      await page.reload();
    });
    await expect(copilotStatus).toHaveCount(0);
  } finally {
    if (restoreCopilot && !page.isClosed()) {
      const currentSessionId = await studioEditorSessionId(page).catch(() => sessionId);
      await saveCopilot(false, currentSessionId);
    }
  }
  await recoverWorkspaceEventStream(replacedWorkspaceStreams);
  closedCopilotTransport.recovered();
});

test("static WebAssembly executes the mounted dependency closure", async ({ page }) => {
  await page.goto(staticExportUrl);
  const status = page.locator("#projected-status");

  await expect(status).toHaveAttribute("data-state", "ready", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });
  await expect(status).toHaveText("clean");
  await expect(page.locator("#escaped-slash")).toHaveText("slash");
  await expect(page.locator("#surrogate-pair")).toHaveText("emoji");
});

test("explains a degraded runtime diagnostic in the runtime menu", async ({ page }) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  await page.evaluate((lifecycleQueryParam) => {
    const frame = document.querySelector<HTMLIFrameElement>(
      'iframe[data-preview-runtime-frame="server"]',
    );
    if (!frame?.contentWindow) {
      throw new Error("Server preview frame is unavailable");
    }
    const lifecycleId = Number(new URL(frame.src).searchParams.get(lifecycleQueryParam));
    if (!Number.isInteger(lifecycleId) || lifecycleId <= 0) {
      throw new Error("Server preview lifecycle is unavailable");
    }
    globalThis.dispatchEvent(
      new MessageEvent("message", {
        origin: globalThis.location.origin,
        source: frame.contentWindow,
        data: {
          type: "marimo-studio:view-diagnostics",
          runtime: "server",
          lifecycleId,
          view: "dashboard",
          diagnostics: [
            {
              code: "value-stale",
              severity: "warning",
              message: "The projected value is stale.",
              hint: "Wait for the notebook to finish running.",
              view: "dashboard",
              scope: "projection",
              projection: "value",
              target: "metric",
              source: { path: "dashboard.html", line: 12, column: 4 },
            },
          ],
        },
      }),
    );
  }, DOCUMENT_LIFECYCLE_QUERY_PARAM);

  const trigger = page.getByLabel("Python preview runtime");
  await expect(trigger).toContainText("Live with 1 warning");
  await trigger.click();
  const status = trigger.locator("..").getByRole("status", { name: "Preview runtime status" });
  await expect(status).toBeVisible();
  await expect(status).toContainText("Live with 1 warning");
  await expect(status).toContainText("The projected value is stale.");
  await expect(status).toContainText("metric");
  await expect(status).toContainText("dashboard.html:12:4");
  await expect(status).toContainText("Wait for the notebook to finish running.");
});

test("preserves native output state across HTML edits and replaces terminal failures", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(210_000);
  const staleOutputs = browserDiagnostics.expectResponse({
    status: 409,
    path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/outputs$/,
    error: "stale-projection-binding",
    count: 3,
    required: false,
  });
  const refreshedOutputs = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "POST",
    path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/outputs$/,
    count: 3,
    required: false,
  });
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  const serverSummary = server.locator("#rich-summary-output");
  const wasmSummary = wasm.locator("#rich-summary-output");
  const serverTable = server.locator('marimo-output[value="rich_table"]');
  const wasmTable = wasm.locator('marimo-output[value="rich_table"]');
  const serverLongOutput = server.locator("#long-output");
  const wasmLongOutput = wasm.locator("#long-output");
  const columns = serverTable.getByRole("button", { name: "Columns" });
  const wasmColumns = wasmTable.getByRole("button", { name: "Columns" });
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmSummary).toHaveAttribute("data-state", "ready", { timeout: 45_000 });
  await expect(serverLongOutput).toContainText("Long selector ready");
  await expect(wasmLongOutput).toContainText("Long selector ready");
  await wasmColumns.click();
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");
  await activateServerPreview(page, browserDiagnostics);
  await columns.click();
  await expect(columns).toHaveAttribute("aria-expanded", "true");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const layoutEdit = source.replace("Studio browser fixture</h1>", "Edited layout</h1>");
  await writeDashboardSource(page, layoutEdit);
  await expect(server.getByRole("heading", { name: "Edited layout" })).toBeVisible();
  await expect(columns).toHaveAttribute("aria-expanded", "true");
  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  await expect(wasm.getByRole("heading", { name: "Edited layout" })).toBeVisible();
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");

  const unavailable = layoutEdit.replace('value="rich_summary"', 'value="missing_output"');
  await writeDashboardSource(page, unavailable);
  await expect(wasmSummary).toHaveAttribute("data-state", "error");
  await expect(wasmSummary).toHaveAttribute(
    "data-marimo-diagnostic-code",
    "projection-output-variable-not-found",
  );
  await expect(wasmSummary).toContainText("does not resolve in this notebook");
  await activateServerPreview(page, browserDiagnostics);
  await expect(serverSummary).toHaveAttribute("data-state", "error");
  await expect(serverSummary).toHaveAttribute(
    "data-marimo-diagnostic-code",
    "projection-output-variable-not-found",
  );
  await expect(serverSummary).toContainText("does not resolve in this notebook");

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  await waitForPreview(page, "wasm");
  const unavailableRevision = await wasm
    .locator("html")
    .evaluate(() => globalThis.marimoStudio.identity().revision);
  await writeDashboardSource(page, layoutEdit);
  await expect
    .poll(() => wasm.locator("html").evaluate(() => globalThis.marimoStudio.identity().revision))
    .not.toBe(unavailableRevision);
  await waitForPreview(page, "wasm");
  await expect(wasmSummary).toHaveAttribute("data-state", "ready");
  await expect(wasmSummary.locator("h3")).toHaveText("Current total: 42");
  await expect(wasmColumns).toHaveAttribute("aria-expanded", "true");
  await activateServerPreview(page, browserDiagnostics);
  await expect(serverSummary).toHaveAttribute("data-state", "ready");
  await expect(serverSummary.locator("h3")).toHaveText("Current total: 42");
  await expect(columns).toHaveAttribute("aria-expanded", "true");
  staleOutputs.recovered();
  await recoverRequestAbort(refreshedOutputs);
});

test("preserves projected controls across refresh and owner removal", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(210_000);
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const serverFresh = server.locator("#fresh-control").getByRole("slider");
  const serverMixed = server.locator("#mixed-controls").getByRole("slider");
  const serverSharedOwner = server.locator("#shared-control-owner");

  await expect(serverFresh).toHaveAttribute("aria-valuenow", "2");
  await expect(serverMixed).toHaveCount(2);
  await expect(serverSharedOwner).toHaveAttribute("data-state", "ready");

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  await expectPreviewInteractive(page, "wasm");
  const wasmFresh = wasm.locator("#fresh-control").getByRole("slider");
  const wasmMixed = wasm.locator("#mixed-controls").getByRole("slider");
  const wasmSharedOwner = wasm.locator("#shared-control-owner");
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "2", { timeout: 45_000 });
  await expect(wasmMixed).toHaveCount(2);
  await expect(wasmSharedOwner).toHaveAttribute("data-state", "ready");
  await activateServerPreview(page, browserDiagnostics);

  await serverMixed.nth(1).press("End");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  const scale = editorSlider(page);
  await scale.press("Home");
  await expect(scale).toHaveAttribute("aria-valuenow", "1");
  await expect(serverFresh).toHaveAttribute("aria-valuenow", "1");
  await expect(serverMixed.nth(0)).toHaveAttribute("aria-valuenow", "1");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  await expectPreviewInteractive(page, "wasm");
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "1");
  await expect(wasmMixed.nth(0)).toHaveAttribute("aria-valuenow", "1");
  await expect(wasmMixed.nth(1)).toHaveAttribute("aria-valuenow", "1");
  await wasmMixed.nth(1).press("End");

  await scale.press("End");
  await expect(scale).toHaveAttribute("aria-valuenow", "3");
  await expect(wasmFresh).toHaveAttribute("aria-valuenow", "3");
  await expect(wasmMixed.nth(0)).toHaveAttribute("aria-valuenow", "3");
  await expect(wasmMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  await activateServerPreview(page, browserDiagnostics);
  await expect(serverFresh).toHaveAttribute("aria-valuenow", "3");
  await expect(serverMixed.nth(0)).toHaveAttribute("aria-valuenow", "3");
  await expect(serverMixed.nth(1)).toHaveAttribute("aria-valuenow", "3");

  const source = await readWorkspaceFile(dashboardHtmlPath);
  const withoutOwner = source.replace(
    '      <marimo-output id="shared-control-owner" value="projected_control"></marimo-output>\n',
    "",
  );
  await writeDashboardSource(page, withoutOwner);

  for (const [index, preview] of [server, wasm].entries()) {
    if (index > 0) {
      await page.getByLabel("Python preview runtime").click();
      await page.getByRole("button", { name: /Browser/ }).click();
    }
    await expectPreviewInteractive(page, index === 0 ? "server" : "wasm");
    const owner = preview.locator("#shared-control-owner");
    const consumer = preview.locator("#shared-control-consumer");
    const peer = preview.locator("#shared-control-peer");
    await expect(owner).toHaveCount(0);
    await expect(consumer).toHaveAttribute("data-state", "ready");
    await expect(peer).toHaveAttribute("data-state", "ready");
    await preview.locator("html").evaluate(
      () =>
        new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }),
    );
    const slider = consumer.getByRole("slider");
    await slider.press("End");
    await expect(slider).toHaveAttribute("aria-valuenow", "3");
    await expect(peer.getByRole("slider")).toHaveAttribute("aria-valuenow", "3");
  }
});

test("preserves runtime state while modes and controls change", async ({
  browserDiagnostics,
  page,
}) => {
  test.setTimeout(210_000);
  const supersededDocuments = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/(?:_marimo-studio\/presentation\/[^/]+\/)?dashboard\/$/,
    count: 2,
    required: false,
  });
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const serverWidget = server.getByRole("button", { name: /Widget count:/ });
  await expect(serverWidget).toHaveText(/^Widget count: \d+$/);
  const serverWidgetCount = Number((await serverWidget.textContent())?.split(": ").at(-1));
  await serverWidget.click();
  await expect(serverWidget).toHaveText(`Widget count: ${serverWidgetCount + 1}`);

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  const wasmWidget = wasm.getByRole("button", { name: /Widget count:/ });
  await expect(wasmWidget).toHaveText(/^Widget count: \d+$/);
  const wasmWidgetCount = Number((await wasmWidget.textContent())?.split(": ").at(-1));
  await wasmWidget.click();
  await expect(wasmWidget).toHaveText(`Widget count: ${wasmWidgetCount + 1}`);

  const editorElement = await page.locator('iframe[title="Marimo editor"]').elementHandle();
  const serverElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const wasmElement = await page
    .locator('iframe[data-preview-runtime-frame="wasm"]')
    .elementHandle();
  expect(editorElement).not.toBeNull();
  expect(serverElement).not.toBeNull();
  expect(wasmElement).not.toBeNull();

  await activateServerPreview(page, browserDiagnostics);
  for (const mode of ["Notebook", "Preview", "Develop", "Notebook", "Develop"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
  }

  const currentEditor = await page.locator('iframe[title="Marimo editor"]').elementHandle();
  const currentServer = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const currentWasm = await page
    .locator('iframe[data-preview-runtime-frame="wasm"]')
    .elementHandle();
  expect(
    await page.evaluate(([before, after]) => before === after, [editorElement, currentEditor]),
  ).toBe(true);
  expect(
    await page.evaluate(([before, after]) => before === after, [serverElement, currentServer]),
  ).toBe(true);
  expect(
    await page.evaluate(([before, after]) => before === after, [wasmElement, currentWasm]),
  ).toBe(true);
  await expect(page.locator('iframe[data-preview-runtime-frame="server"]')).toBeVisible();
  await expect(page.locator('iframe[data-preview-runtime-frame="wasm"]')).toHaveAttribute(
    "inert",
    "",
  );
  await expect(serverWidget).toHaveText(`Widget count: ${serverWidgetCount + 1}`);
  await expect(wasm.locator("button").filter({ hasText: /Widget count:/ })).toHaveText(
    `Widget count: ${wasmWidgetCount + 1}`,
  );
  await recoverRequestAbort(supersededDocuments);
});

test("keeps native output ownership isolated between server preview consumers", async ({
  page,
}) => {
  await page.goto(studioEntryUrl);
  const embedded = await waitForPreview(page);
  const popoutOpened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await popoutOpened;
  await popout.waitForLoadState("domcontentloaded");
  expect(await popout.evaluate(() => globalThis.opener)).toBeNull();
  const popoutPresentation = presentationFrame(popout);
  await waitForPresentationRuntime(popoutPresentation);

  const embeddedTable = embedded.locator('marimo-output[value="rich_table"]');
  const popoutTable = popoutPresentation.locator('marimo-output[value="rich_table"]');
  await embeddedTable.getByRole("button", { name: "Columns" }).click();
  await popoutTable.getByRole("button", { name: "Columns" }).click();
  await expect(embeddedTable.getByRole("button", { name: "Columns" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await expect(popoutTable.getByRole("button", { name: "Columns" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  await editorSlider(page).press("End");
  await expect(embeddedTable).toContainText("63");
  await expect(popoutTable).toContainText("63");
  await popoutPresentation.locator("#rich-summary-output").evaluate((host) => host.remove());
  await expect(embedded.locator("#rich-summary-output")).toHaveAttribute("data-state", "ready");

  await popout.close();
  const embeddedColumns = embeddedTable.getByRole("button", { name: "Columns" });
  await embeddedColumns.click();
  await expect(embeddedColumns).toHaveAttribute("aria-expanded", "true");
});

test("refreshes a popout view and preserves its public query across reload", async ({
  browserDiagnostics,
  page,
}) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const popoutOpened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await popoutOpened;
  await popout.waitForLoadState("domcontentloaded");
  const rendered = presentationFrame(popout);

  try {
    await waitForPresentationRuntime(rendered);
    const source = await readWorkspaceFile(dashboardHtmlPath);
    const refreshed = source.replace(
      "<h1>Studio browser fixture</h1>",
      `<h1>Popout live view</h1>
      <a href="?region=apac">APAC</a>
      <p>Region: <strong id="popout-region" mo-value='query_params["region"]'></strong></p>`,
    );
    const retiredDevelopmentStream = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin,
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/dev\/events$/,
      count: 1,
      status: 200,
    });
    const refreshedProjectionReads = browserDiagnostics.expectRequestAbort({
      origin: studioOrigin,
      method: "POST",
      path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/(?:values|outputs)$/,
      count: 2,
      required: false,
    });
    await writeDashboardSource(page, refreshed);

    await expect(rendered.getByRole("heading", { name: "Popout live view" })).toBeVisible();
    await expect(rendered.locator('strong[mo-value="metric"]')).toHaveText("42");
    await waitForPresentationRuntime(rendered);
    await previewFrame(page).getByRole("link", { name: "APAC", exact: true }).click();
    await expect(page).toHaveURL(/region=apac/);
    await expect(popout).toHaveURL(/region=apac/);
    await expect(rendered.locator("#popout-region")).toHaveText("apac");
    await rendered.locator("html").evaluate(() => {
      const target = new URL(globalThis.location.href);
      target.searchParams.set("region", "apac");
      target.searchParams.set("file", "forged.py");
      target.searchParams.set("marimo_studio_server", "private-server");
      target.searchParams.set("access_token", "private-token");
      globalThis.history.replaceState(globalThis.history.state, "", target);
    });
    await expect(popout).toHaveURL(/\/dashboard\/\?file=notebook\.py&region=apac$/);
    const publicUrl = new URL(popout.url());
    expect(publicUrl.searchParams.get("file")).toBe("notebook.py");
    expect(publicUrl.searchParams.get("region")).toBe("apac");
    expect(publicUrl.searchParams.has("marimo_studio_server")).toBe(false);
    expect(publicUrl.searchParams.has("access_token")).toBe(false);

    const preReloadDocument = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin,
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      count: 1,
    });
    await popout.reload();
    await waitForPresentationRuntime(rendered);
    await expect(rendered.getByRole("heading", { name: "Popout live view" })).toBeVisible();
    expect(
      await rendered.locator("html").evaluate(() => {
        const query = new URLSearchParams(globalThis.location.search);
        return query.get("region");
      }),
    ).toBe("apac");
    await expect(rendered.locator("#popout-region")).toHaveText("apac");
    await expect(rendered.locator('strong[mo-value="metric"]')).toHaveText("42");
    await recoverRequestAbort(refreshedProjectionReads);
    await recoverRequestAbort(preReloadDocument);
    await recoverRequestAbort(retiredDevelopmentStream);
  } finally {
    if (!popout.isClosed()) {
      const retirement = browserDiagnostics.expectPageRetirement(popout);
      await popout.close();
      retirement.recovered();
    }
  }
});
