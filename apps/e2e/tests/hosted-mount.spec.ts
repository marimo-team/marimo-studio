import { runtimeConfigSchema } from "@marimo-studio/protocol/runtime-config";
import { viewProjectSchema } from "@marimo-studio/protocol/view-project";
import { readFile } from "node:fs/promises";
import { z } from "zod";

import { studioClientId, studioEditorSessionId } from "./authoring-test-support.ts";
import {
  selectWorkspaceMode,
  editorSlider,
  expect,
  hostedOrigin,
  hostedViewFixturePath,
  labeledSlider,
  previewFrame,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  studioServerToken,
  test,
  waitForPreview,
} from "./fixture.ts";

const baseUrl = () => `${hostedOrigin()}/hosted`;
const accessToken = "studio-e2e-token";

test.use({ services: ["hosted"] });

test("captures a fresh HTML view through an authenticated hosted mount", async ({
  browserDiagnostics,
  page,
}) => {
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    `${baseUrl()}/_marimo-studio/dev/events`,
    1,
  );
  await page.goto(`${baseUrl()}/studio/?access_token=${accessToken}`);
  await page.getByText("Add view", { exact: true }).click();
  await page.getByRole("radio", { name: /^HTML document/ }).check();
  await page.getByRole("button", { name: "Create view" }).click();
  await waitForPreview(page);

  const clientId = await studioClientId(page);
  const response = await page.request.get(`${baseUrl()}/_marimo-studio/views/dashboard/config`, {
    params: { runtime: "zero-python", marimo_studio_client: clientId },
    headers: { "Marimo-Studio-Preview-Session-Id": "s_export" },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const config = runtimeConfigSchema.parse(await response.json());
  expect(config.runtime.id).toBe("zero-python");
  const manifest = await page.request.get(
    new URL(z.string().parse(config.runtime.data.manifestUrl), baseUrl()).href,
  );
  expect(manifest.ok(), await manifest.text()).toBe(true);
  expect(await manifest.json()).toMatchObject({
    schema: "marimo-studio.prepared.v1",
    view: "dashboard",
  });

  const controls = await page.request.get(`${baseUrl()}/_marimo-studio/views/dashboard/controls`, {
    params: { revision: config.revision, marimo_studio_client: clientId },
    headers: { "Marimo-Session-Id": await studioEditorSessionId(page) },
  });
  expect(controls.ok(), await controls.text()).toBe(true);
  expect(Object.values((await controls.json()).controls.bindings)).toContainEqual({
    input: "scale",
    path: [],
  });
  await page.getByLabel(/preview runtime$/).click();
  const retiredManifest = browserDiagnostics.expectRequestAbort({
    origin: hostedOrigin(),
    method: "GET",
    path: /^\/hosted\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/zero-python\/current$/,
    count: 1,
    required: false,
    status: 200,
  });
  await page.getByRole("button", { name: /Prepared/ }).click();
  const prepared = await waitForPreview(page, "zero-python");
  await expect(prepared.getByRole("heading", { name: "Hosted total: 42" })).toBeVisible();
  await expect(page.getByRole("status", { name: "View status" })).toContainText("Live");
  await recoverRequestAbort(retiredManifest);
  await recoverWorkspaceEventStream(replacedWorkspaceStream);
});

test("initializes and runs Studio through an authenticated hosted mount", async ({
  browserDiagnostics,
  page,
}) => {
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    `${baseUrl()}/_marimo-studio/dev/events`,
    2,
  );
  const interruptedDocumentTransaction = browserDiagnostics.expectRequestFailure({
    origin: hostedOrigin(),
    path: /^\/hosted\/(?:_marimo-studio\/editor\/)?api\/document\/transaction$/,
    method: "POST",
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  const interruptedDocumentTransactionLog = browserDiagnostics.expectConsole({
    type: "error",
    text: /^Failed to handle request: sendDocumentTransaction TypeError: Failed to fetch/,
    required: false,
  });
  const unusedNativeImages = browserDiagnostics.expectConsole({
    type: "warning",
    text: /^The resource http:\/\/127\.0\.0\.1:\d+\/hosted\/assets\/(?:gradient|noise)-[^/\s]+\.png was preloaded using link preload but not used/,
    count: 2,
    required: false,
  });
  await expect
    .poll(
      async () =>
        fetch(`${baseUrl()}/?access_token=${accessToken}`, { redirect: "manual" })
          .then((response) => response.status)
          .catch(() => 0),
      { timeout: 30_000 },
    )
    .toBe(303);

  await page.goto(`${baseUrl()}/?access_token=${accessToken}`);
  await expect(page).toHaveURL(`${baseUrl()}/`);
  await expect(page.locator("[data-cell-id]").first()).toBeVisible();
  await expect(page.locator("#marimo-studio-host")).toHaveCount(0);
  await page.getByTestId("run-button").last().click();
  const nativeScale = labeledSlider(page.locator("body"), /^Hosted scale/);
  await nativeScale.press("End");
  await expect(nativeScale).toHaveAttribute("aria-valuenow", "3");

  await page.goto(`${baseUrl()}/studio/`);
  await expect(page).toHaveURL(`${baseUrl()}/studio/`);
  await expect(page.getByText("Add view", { exact: true })).toBeVisible();
  await page.getByText("Add view", { exact: true }).click();
  await expect(page.locator('iframe[title="Marimo editor"]')).not.toHaveAttribute("inert");
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 375, height: 812 },
  ]) {
    await page.setViewportSize(viewport);
    await expect(page.getByRole("textbox", { name: "New view" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await page.setViewportSize({ width: 1280, height: 720 });

  const before = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl()}/_marimo-studio/status`);
  expect(before).toEqual({
    schema: 1,
    state: "needs-view",
    default_view: "dashboard",
    views: [],
  });

  await page.getByRole("radio", { name: /^HTML document/ }).check();
  await page.getByRole("button", { name: "Create view" }).click();
  await expect(page).toHaveURL(`${baseUrl()}/studio/dashboard/`);
  await expect(editorSlider(page, /^Hosted scale/)).toHaveAttribute("aria-valuenow", "3");
  await expect(page.getByLabel("Switch view")).toContainText("dashboard");

  const after = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl()}/_marimo-studio/status`);
  expect(after).toEqual({
    schema: 1,
    state: "ready",
    default_view: "dashboard",
    views: ["dashboard"],
  });

  await waitForPreview(page);
  unusedNativeImages.recovered();
  const previewElement = await page
    .locator('iframe[data-preview-runtime-frame="server"]')
    .elementHandle();
  const retiringFrame = await previewElement
    ?.contentFrame()
    .finally(() => previewElement.dispose());
  if (!retiringFrame) throw new Error("The hosted preview frame is unavailable.");
  const retirement = browserDiagnostics.expectFrameRetirement(retiringFrame);
  await page.goto(`${baseUrl()}/`);
  await expect(page.locator("[data-cell-id]").first()).toBeVisible();
  retirement.recovered();
  await page.goto(`${baseUrl()}/studio/dashboard/`);
  await expect(editorSlider(page, /^Hosted scale/)).toHaveAttribute("aria-valuenow", "3");
  const preview = await waitForPreview(page);
  const replacement = await readFile(hostedViewFixturePath, "utf8");
  const serverToken = await studioServerToken(page);
  const supersededConfigRead = browserDiagnostics.expectActiveRequestAbort({
    origin: hostedOrigin(),
    method: "GET",
    path: /^\/hosted\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/config$/,
    count: 1,
  });
  const abandonedSourceWrite = browserDiagnostics.expectRequestAbort({
    origin: hostedOrigin(),
    method: "PUT",
    path: /^\/hosted\/_marimo-studio\/views\/dashboard\/source\/index\.html$/,
    count: 1,
    status: 204,
  });
  const projectResponse = await page.request.get(
    `${baseUrl()}/_marimo-studio/views/dashboard/project`,
  );
  expect(projectResponse.ok()).toBe(true);
  const project = viewProjectSchema.parse(await projectResponse.json());
  const saved = await page.evaluate(
    async ({ catalogGeneration, content, sourceUrl, token, viewGeneration }) => {
      const current = await fetch(sourceUrl, { cache: "no-store" });
      const revision = current.headers.get("ETag");
      if (!current.ok || !revision) {
        return current.status;
      }
      const response = await fetch(sourceUrl, {
        method: "PUT",
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "If-Match": revision,
          "Marimo-Server-Token": token,
          "Marimo-Studio-Catalog-Generation": catalogGeneration,
          "Marimo-Studio-View-Generation": viewGeneration,
        },
        body: content,
      });
      return response.status;
    },
    {
      catalogGeneration: project.catalog_generation,
      content: replacement,
      sourceUrl: `${baseUrl()}/_marimo-studio/views/dashboard/source/index.html`,
      token: serverToken,
      viewGeneration: project.view_generation,
    },
  );
  expect(saved).toBe(204);
  await expect(preview.getByRole("heading", { name: "Hosted mount lifecycle" })).toBeVisible();
  const persisted = await page.request.get(
    `${baseUrl()}/_marimo-studio/views/dashboard/source/index.html`,
  );
  expect(persisted.ok()).toBe(true);
  expect(await persisted.text()).toBe(replacement);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Focus Source", exact: true }).click();
  await page.getByRole("tab", { name: "index.html" }).click();
  await expect(page.getByLabel("index.html source")).toContainText("Hosted mount lifecycle");
  await expect(
    page
      .getByRole("region", { name: "Source" })
      .getByRole("status", { name: "Source document status" }),
  ).toHaveText("Saved");

  await selectWorkspaceMode(page, "Notebook");
  await expect(page.locator('iframe[title="Marimo editor"]')).toBeVisible();
  const scale = editorSlider(page, /^Hosted scale/);
  await expect(scale).toBeVisible();
  const value = previewFrame(page).locator('[mo-value="metric"]');
  await scale.press("Home");
  await expect(value).toHaveText("21");
  await scale.press("End");
  await expect(value).toHaveText("63");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Hosted mount lifecycle" })).toBeVisible();
  await expect(value).toHaveText("63");

  await recoverRequestAbort(supersededConfigRead);
  await recoverRequestAbort(abandonedSourceWrite);
  interruptedDocumentTransaction.recovered();
  interruptedDocumentTransactionLog.recovered();
  replacedWorkspaceStream.recovered();
});
