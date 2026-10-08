import type { Page } from "@playwright/test";

import { readFile, writeFile } from "node:fs/promises";

import { proxiedNotebookPath } from "../scripts/paths.ts";
import { saveShortcut, selectAllShortcut } from "./authoring-test-support.ts";
import {
  type BrowserDiagnostics,
  captureRetiringPreviewReads,
  editorSlider,
  expect,
  expectPreviewRevisionSwap,
  labeledSlider,
  presentationFrame,
  previewFrame,
  proxiedFixturePath,
  proxiedUrl,
  proxiedWorkspacePath,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  test,
  waitForPreview,
  WASM_PREVIEW_TIMEOUT,
} from "./fixture.ts";

// The proxy publishes `marimo edit --no-token` beneath a random /s/<id>/p/<id>/
// prefix, strips it before forwarding, and rewrites Host to the backend. The
// browser fixture fails the test when any request leaves that prefix.
test.use({ services: ["proxied"] });

const createDashboard = async (page: Page, diagnostics: BrowserDiagnostics) => {
  // Opening the first view replaces the host's workspace event stream.
  const replacedStream = diagnostics.expectWorkspaceEventStreamReplacement(
    `${proxiedUrl()}_marimo-studio/dev/events`,
  );
  await page.goto(proxiedUrl());
  await page.getByText("Add view", { exact: true }).click();
  await page.getByRole("radio", { name: /^HTML document/ }).check();
  await page.getByRole("button", { name: "Create view" }).click();
  await expect(page).toHaveURL(`${proxiedUrl()}studio/dashboard/`);
  const preview = await waitForPreview(page);
  await recoverWorkspaceEventStream(replacedStream);
  return preview;
};

const dashboardSourcePath = () =>
  proxiedWorkspacePath("__marimo__/studio/notebook/dashboard/index.html");

const proxiedPath = (suffix: string) =>
  new RegExp(`^${new URL(proxiedUrl()).pathname.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}${suffix}$`);

// Saves the dashboard through the Source editor, whose requests resolve
// beneath the proxy prefix.
const replaceDashboardSource = async (page: Page, diagnostics: BrowserDiagnostics) => {
  const retiringReads = await captureRetiringPreviewReads(page, diagnostics);
  // Saving retires the editor's earlier write for the same document.
  const replacedSourceWrite = diagnostics.expectRequestAbort({
    origin: new URL(proxiedUrl()).origin,
    method: "PUT",
    path: proxiedPath("_marimo-studio/views/dashboard/source/index\\.html"),
    count: 1,
    required: false,
    status: 204,
  });
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  const editor = page.getByLabel("index.html source");
  await editor.focus();
  await editor.press(selectAllShortcut);
  await page.keyboard.insertText(await readFile(proxiedFixturePath("dashboard.html"), "utf8"));
  await editor.press(saveShortcut);
  await expect(
    page.getByRole("region", { name: "Source" }).getByRole("status", {
      name: "Source document status",
    }),
  ).toHaveText("Saved");
  await expect(
    previewFrame(page).getByRole("heading", { name: "Proxied dashboard" }),
  ).toBeVisible();
  retiringReads.recovered();
  await recoverRequestAbort(replacedSourceWrite);
};

// Control discovery can start while the runtime menu is open.
const selectPreviewRuntime = async (
  page: Page,
  diagnostics: BrowserDiagnostics,
  runtime: "Prepared" | "Browser",
) => {
  const controls = diagnostics.expectRequestAbort({
    origin: new URL(proxiedUrl()).origin,
    method: "GET",
    path: proxiedPath("_marimo-studio/views/dashboard/controls"),
    count: 1,
    required: false,
  });
  await page.getByLabel(/preview runtime$/).click();
  await page.getByRole("button", { name: new RegExp(`^${runtime}`) }).click();
  const preview = await waitForPreview(
    page,
    runtime === "Prepared" ? "zero-python" : "wasm",
    runtime === "Prepared" ? undefined : WASM_PREVIEW_TIMEOUT,
  );
  await recoverRequestAbort(controls);
  return preview;
};

test("creates, edits, and previews a view beneath a stripped proxy prefix", async ({
  browserDiagnostics,
  page,
}) => {
  await createDashboard(page, browserDiagnostics);
  const preview = previewFrame(page);
  await expect(editorSlider(page, /^Proxied scale/)).toHaveAttribute("aria-valuenow", "2");

  await replaceDashboardSource(page, browserDiagnostics);

  const metric = preview.locator('[mo-value="metric"]');
  await expect(metric).toHaveText("42");
  await labeledSlider(preview.locator("body"), /^Proxied scale/).press("End");
  await expect(metric).toHaveText("63");
  await expect(editorSlider(page, /^Proxied scale/)).toHaveAttribute("aria-valuenow", "3");
  await editorSlider(page, /^Proxied scale/).press("Home");
  await expect(metric).toHaveText("21");

  await page.getByLabel("Workspace options", { exact: true }).click();
  const standalone = page.getByRole("link", { name: "Open preview in new tab" });
  const standaloneUrl = await standalone.getAttribute("href");
  expect(standaloneUrl?.startsWith(`${proxiedUrl()}dashboard/?`)).toBe(true);
  await page.keyboard.press("Escape");
  const tab = await page.context().newPage();
  await tab.goto(standaloneUrl!);
  // The standalone wrapper replaces private routing state with the public URL.
  await expect(tab).toHaveURL(`${proxiedUrl()}dashboard/`);
  const standaloneView = presentationFrame(tab);
  await expect(standaloneView.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  await expect(standaloneView.locator('[mo-value="metric"]')).toHaveText("21");
  await tab.close();
});

test("switches preview runtimes beneath a stripped proxy prefix", async ({
  browserDiagnostics,
  page,
}) => {
  await createDashboard(page, browserDiagnostics);
  await replaceDashboardSource(page, browserDiagnostics);

  // A retained Prepared frame keeps polling its publication, so Browser starts
  // first and Prepared opens last.
  const browser = await selectPreviewRuntime(page, browserDiagnostics, "Browser");
  await expect(browser.locator('[mo-value="metric"]')).toHaveText("42", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });

  const prepared = await selectPreviewRuntime(page, browserDiagnostics, "Prepared");
  await expect(prepared.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  await expect(prepared.locator('[mo-value="metric"]')).toHaveText("42");
});

// An agent shares a preview URL, then rewrites the view source on disk. The
// open tab follows each build and keeps the public address it was given.
for (const runtime of ["server", "wasm", "zero-python"] as const) {
  test(`keeps a ${runtime} preview URL live beneath a stripped proxy prefix`, async ({
    browserDiagnostics,
    page,
    studioCli,
  }) => {
    await createDashboard(page, browserDiagnostics);
    const timeout = runtime === "wasm" ? WASM_PREVIEW_TIMEOUT : 65_000;

    const url = await studioCli.previewView(
      proxiedNotebookPath,
      proxiedUrl(),
      "dashboard",
      runtime,
    );

    expect(url.startsWith(`${proxiedUrl()}dashboard/?`)).toBe(true);
    const tab = await page.context().newPage();
    await tab.goto(url);
    await expect(tab.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
      timeout,
    });
    const viewPath = new URL(`${proxiedUrl()}dashboard/`).pathname;
    expect(new URL(tab.url()).pathname).toBe(viewPath);

    const revisionSwap = await expectPreviewRevisionSwap(
      browserDiagnostics,
      tab,
      proxiedUrl(),
      "dashboard",
    );
    await writeFile(dashboardSourcePath(), await readFile(proxiedFixturePath("dashboard.html")));

    await expect(tab.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible({
      timeout,
    });
    const metric = tab.locator('[mo-value="metric"]');
    await expect(metric).toHaveText("42", { timeout });
    expect(new URL(tab.url()).pathname).toBe(viewPath);
    if (runtime !== "zero-python") {
      await labeledSlider(tab.locator("body"), /^Proxied scale/).press("End");
      await expect(metric).toHaveText("63");
    }
    await revisionSwap();
    await tab.close();
  });
}
