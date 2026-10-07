import type { Page } from "@playwright/test";

import { randomUUID } from "node:crypto";
import { rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";

import { runCellShortcut, selectAllShortcut, studioClientId } from "./authoring-test-support.ts";
import {
  selectWorkspaceMode,
  dashboardHtmlPath,
  expect,
  expectPreviewInteractive,
  editorFrame,
  previewFrame,
  PREVIEW_TIMEOUT,
  readWorkspaceFile,
  studioEntryUrl,
  studioOrigin,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
  writeDashboardSource,
} from "./fixture.ts";

test.describe.configure({ timeout: 150_000 });

const allowRuntimePendingProjectionReads = (browserDiagnostics: {
  expectResponse: (expectation: {
    status: number;
    path: RegExp;
    error: string;
    count: number;
    required: boolean;
  }) => { recovered: () => void };
}) =>
  browserDiagnostics.expectResponse({
    status: 409,
    path: /\/(?:values|outputs)$/,
    error: "runtime-sync-pending",
    count: 128,
    required: false,
  });

test("keeps the startup document while runtime configuration is pending", async ({
  browserDiagnostics,
  page,
}) => {
  const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
  let release!: () => void;
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  let intercepted!: () => void;
  const pending = new Promise<void>((resolve) => {
    intercepted = resolve;
  });
  let held = false;
  await page.clock.install();
  await page.route(/\/_marimo-studio\/views\/dashboard\/config(?:\?|$)/, async (route) => {
    if (held || route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    held = true;
    intercepted();
    await released;
    await route.continue();
  });
  try {
    await page.goto(studioEntryUrl);
    await pending;
    const frame = page.locator('iframe[data-preview-runtime-frame="server"]');
    const documentUrl = await frame.getAttribute("src");
    await expect(
      page.getByRole("progressbar", { name: "Connecting to the Python runtime" }),
    ).toBeVisible();
    await page.clock.runFor(11_000);
    await expect(frame).toHaveAttribute("src", documentUrl!);
    release();
    await waitForPreview(page);
    await expectPreviewInteractive(page, "server");
    await expect(
      page.getByRole("progressbar", { name: "Connecting to the Python runtime" }),
    ).toHaveCount(0);
    pendingProjectionReads.recovered();
  } finally {
    release();
  }
});

test("shows a startup failure and retries configuration on request", async ({
  browserDiagnostics,
  page,
}) => {
  const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
  const failedConfig = browserDiagnostics.expectResponse({
    status: 409,
    path: /\/_marimo-studio\/views\/dashboard\/config$/,
    error: "publication-error",
  });
  const failedStartup = browserDiagnostics.expectConsole({
    type: "error",
    text: /^marimo-studio runtime error /,
  });
  let failed = false;
  await page.route(/\/_marimo-studio\/views\/dashboard\/config\?/, async (route) => {
    if (failed || route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    failed = true;
    await route.fulfill({
      status: 409,
      json: {
        error: "publication-error",
        message: "Notebook states could not be captured.",
        hint: "Check the notebook outputs, then retry.",
        context: { state: "baseline", input: "data/records.csv" },
      },
    });
  });
  await page.goto(studioEntryUrl);
  const failure = page.getByRole("alert").filter({ hasText: "Python runtime could not start" });
  await expect(failure).toContainText("Notebook states could not be captured.");
  await expect(failure).toContainText("Check the notebook outputs, then retry.");
  await failure.getByText("Technical details").click();
  await expect(failure.getByLabel("Diagnostic details")).toContainText('"state": "baseline"');
  await expect(failure.getByLabel("Diagnostic details")).toContainText("data/records.csv");
  await expect(page.getByRole("status", { name: "View status" })).toContainText("Needs repair");
  await page.getByRole("button", { name: "Retry preview" }).click();
  await waitForPreview(page);
  await expectPreviewInteractive(page, "server");
  await expect(failure).toHaveCount(0);
  pendingProjectionReads.recovered();
  failedConfig.recovered();
  failedStartup.recovered();
});

test("keeps the runtime request pending while a notebook cell runs", async ({
  browserDiagnostics,
  page,
}) => {
  const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
  const abortedEvents = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin(),
    method: "GET",
    path: /\/_marimo-studio\/dev\/events(?:\?|$)/,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const gate = `${tmpdir()}/marimo-studio-runtime-pending-${randomUUID()}`;
  await writeFile(gate, "pending");
  const cell = editorFrame(page).locator('[data-cell-name="metric"]');
  const code = cell.getByRole("textbox");
  try {
    await code.click();
    await code.press(selectAllShortcut);
    await page.keyboard.insertText(`from pathlib import Path as _Path
import time as _time
while _Path(${JSON.stringify(gate)}).exists():
    _time.sleep(0.01)
metric = scale.value * 23
metric`);
    await code.press(runCellShortcut);
    await expect(cell.locator("..")).toHaveAttribute("data-status", /queued|running/);

    const clientId = await studioClientId(page);
    const previewSessionId = await page
      .locator('iframe[data-preview-runtime-frame="server"]')
      .getAttribute("data-session-id");
    expect(previewSessionId).toMatch(/^s_[\da-z]{6}$/);
    const response = await page.request.get("/_marimo-studio/views/dashboard/config", {
      params: {
        file: "notebook.py",
        runtime: "server",
        marimo_studio_client: clientId,
      },
      headers: {
        "Marimo-Studio-Preview-Session-Id": previewSessionId!,
      },
    });
    expect(response.status()).toBe(409);
    expect(await response.json()).toMatchObject({
      error: "runtime-sync-pending",
      transient: true,
    });
  } finally {
    await rm(gate, { force: true });
  }
  await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
  await waitForPreview(page);
  await expectPreviewInteractive(page, "server");
  pendingProjectionReads.recovered();
  abortedEvents.recovered();
});

const installRuntimeProgress = (page: Page, initiallyArmed = true) =>
  page.addInitScript((initiallyArmed) => {
    if (globalThis.parent === globalThis.window) return;
    const fetch = globalThis.fetch;
    let armed = initiallyArmed;
    document.addEventListener("test:runtime-arm", () => {
      armed = true;
    });
    globalThis.fetch = async (input, init) => {
      const response = await fetch(input, init);
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (
        !armed ||
        !url.pathname.endsWith("/config") ||
        url.searchParams.get("runtime") !== "server"
      )
        return response;
      armed = false;
      const configuration = await response.arrayBuffer();
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          const report = (completed: number) =>
            controller.enqueue(
              encoder.encode(
                JSON.stringify({
                  type: "progress",
                  progress: { message: "Loading model", completed, total: 4 },
                }) + "\n",
              ),
            );
          controller.enqueue(
            encoder.encode(
              JSON.stringify({
                type: "progress",
                progress: { message: "Inspecting model" },
              }) + "\n",
            ),
          );
          document.addEventListener("test:runtime-start", () => report(1), { once: true });
          document.addEventListener(
            "test:runtime-inspection",
            () => {
              controller.enqueue(
                encoder.encode(
                  JSON.stringify({
                    type: "progress",
                    progress: {
                      message: "Checking model configuration and preparing the remaining inputs",
                    },
                  }) + "\n",
                ),
              );
            },
            { once: true },
          );
          document.addEventListener("test:runtime-progress", () => report(3), { once: true });
          document.addEventListener(
            "test:runtime-complete",
            () => {
              controller.enqueue(new Uint8Array(configuration));
              controller.close();
            },
            { once: true },
          );
        },
      });
      return new Response(stream, { headers: { "content-type": "application/x-ndjson" } });
    };
  }, initiallyArmed);

test("keeps streamed progress with its runtime while switching previews", async ({
  browserDiagnostics,
  page,
}) => {
  const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
  const pendingControls = browserDiagnostics.expectResponse({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/controls(?:\?|$)/,
    count: 2,
    required: false,
  });
  const abortedControls = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin(),
    method: "GET",
    path: /^\/_marimo-studio\/views\/dashboard\/controls(?:\?|$)/,
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  await installRuntimeProgress(page);
  await page.goto(studioEntryUrl);
  const server = previewFrame(page);
  await expect(page.getByRole("progressbar", { name: "Inspecting model" })).toBeVisible({
    timeout: PREVIEW_TIMEOUT,
  });
  await server
    .locator("html")
    .evaluate(() => document.dispatchEvent(new Event("test:runtime-start")));
  const progress = page.getByRole("progressbar", { name: "Loading model" });
  await expect(progress).toHaveAttribute("aria-valuenow", "1");
  await expect(progress).toHaveAttribute("aria-valuemax", "4");
  await expect(page.getByText("1 of 4", { exact: true })).toBeVisible();
  await page.getByLabel(/preview runtime$/).click();
  await page.getByRole("button", { name: /Browser/ }).click();
  await server
    .locator("html")
    .evaluate(() => document.dispatchEvent(new Event("test:runtime-progress")));
  await expect(progress).toHaveCount(0);
  await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  await page.getByLabel(/preview runtime$/).click();
  await page.getByRole("button", { name: /Python Use this editor/ }).click();
  await expect(progress).toHaveAttribute("aria-valuenow", "3");
  await expect(page.getByText("3 of 4", { exact: true })).toBeVisible();
  await server
    .locator("html")
    .evaluate(() => document.dispatchEvent(new Event("test:runtime-complete")));
  await waitForPreview(page);
  await expect(progress).toHaveCount(0);
  await expectPreviewInteractive(page, "server");
  pendingProjectionReads.recovered();
  pendingControls.recovered();
  abortedControls.recovered();
});

for (const width of [1280, 390]) {
  test(`keeps preparation layout stable between stages at ${width}px`, async ({
    browserDiagnostics,
    page,
  }) => {
    const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
    await page.setViewportSize({ width, height: 844 });
    await installRuntimeProgress(page);
    await page.goto(studioEntryUrl);
    if (width === 390) {
      await page.getByRole("combobox", { name: "Visible surface" }).selectOption("preview");
    }
    const preview = previewFrame(page);
    const panel = page.locator(".studio-preview-status-panel");
    const meter = panel.getByRole("progressbar");
    await expect(meter).toBeVisible();
    await expect(meter).toHaveAccessibleName("Inspecting model", { timeout: PREVIEW_TIMEOUT });
    const placement = await meter.boundingBox();
    await preview
      .locator("html")
      .evaluate(() => document.dispatchEvent(new Event("test:runtime-start")));
    await expect(meter).toHaveAttribute("aria-valuenow", "1");
    expect(await meter.boundingBox()).toEqual(placement);
    await preview
      .locator("html")
      .evaluate(() => document.dispatchEvent(new Event("test:runtime-inspection")));
    await expect(panel).toContainText("Checking model");
    await expect(meter).not.toHaveAttribute("aria-valuenow");
    expect(await meter.boundingBox()).toEqual(placement);
    await preview
      .locator("html")
      .evaluate(() => document.dispatchEvent(new Event("test:runtime-complete")));
    await waitForPreview(page);
    await expect(panel).toHaveCount(0);
    pendingProjectionReads.recovered();
  });
}

test("keeps rendered content visible while replacement preparation reports progress", async ({
  browserDiagnostics,
  page,
}) => {
  const pendingProjectionReads = allowRuntimePendingProjectionReads(browserDiagnostics);
  await installRuntimeProgress(page, false);
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  await selectWorkspaceMode(page, "Preview");
  const original = await readWorkspaceFile(dashboardHtmlPath);
  try {
    await preview
      .locator("html")
      .evaluate(() => document.dispatchEvent(new Event("test:runtime-arm")));
    await writeDashboardSource(page, original.replace("</main>", "<p>Updated view</p></main>"));
    const panel = page.locator(".studio-preview-status-panel");
    await expect(panel).toContainText("Inspecting model");
    const metric = preview.locator('strong[mo-value="metric"]');
    await expect(metric).toHaveText("42");
    const outputBox = await metric.boundingBox();
    const panelBox = await panel.boundingBox();
    expect(panelBox!.y).toBeGreaterThan(outputBox!.y + outputBox!.height);
    await preview
      .locator("html")
      .evaluate(() => document.dispatchEvent(new Event("test:runtime-complete")));
    await waitForPreview(page);
    await expect(panel).toHaveCount(0);
    await expect(preview.getByText("Updated view", { exact: true })).toBeVisible();
    pendingProjectionReads.recovered();
  } finally {
    await writeDashboardSource(page, original);
    await waitForPreview(page);
  }
});
