import { viewProjectSchema } from "@marimo-studio/protocol/view-project";
import { readFile } from "node:fs/promises";

import {
  editorSlider,
  expect,
  hostedOrigin,
  hostedViewFixturePath,
  labeledSlider,
  previewFrame,
  recoverRequestAbort,
  studioServerToken,
  test,
  waitForPreview,
} from "./fixture.ts";

const baseUrl = `${hostedOrigin}/hosted`;
const accessToken = "studio-e2e-token";

test.use({ services: ["hosted"] });

test("initializes and runs Studio through an authenticated hosted mount", async ({
  browserDiagnostics,
  page,
}) => {
  const replacedWorkspaceStream = browserDiagnostics.expectWorkspaceEventStreamReplacement(
    `${baseUrl}/_marimo-studio/dev/events`,
    2,
  );
  const interruptedDocumentTransaction = browserDiagnostics.expectRequestFailure({
    origin: hostedOrigin,
    path: /^\/hosted\/_marimo-studio\/editor\/api\/document\/transaction$/,
    method: "POST",
    errorText: "net::ERR_ABORTED",
    required: false,
  });
  const interruptedDocumentTransactionLog = browserDiagnostics.expectConsole({
    type: "error",
    text: /^Failed to handle request: sendDocumentTransaction TypeError: Failed to fetch/,
    required: false,
  });
  await expect
    .poll(
      async () =>
        fetch(`${baseUrl}/?access_token=${accessToken}`, { redirect: "manual" })
          .then((response) => response.status)
          .catch(() => 0),
      { timeout: 30_000 },
    )
    .toBe(303);

  await page.goto(`${baseUrl}/?access_token=${accessToken}`);
  await expect(page).toHaveURL(`${baseUrl}/`);
  await expect(page.locator("[data-cell-id]").first()).toBeVisible();
  await expect(page.locator("#marimo-studio-host")).toHaveCount(0);
  await page.getByTestId("run-button").last().click();
  const nativeScale = labeledSlider(page.locator("body"), /^Hosted scale/);
  await nativeScale.press("End");
  await expect(nativeScale).toHaveAttribute("aria-valuenow", "3");

  await page.goto(`${baseUrl}/studio/`);
  await expect(page).toHaveURL(`${baseUrl}/studio/`);
  await expect(page.getByRole("heading", { name: "Create the first view" })).toBeVisible();
  await expect(page.locator('iframe[title="Marimo editor"]')).toHaveAttribute("inert", "");
  await expect(page.locator('iframe[title="Marimo editor"]')).toHaveAttribute(
    "aria-hidden",
    "true",
  );
  for (const viewport of [
    { width: 1280, height: 720 },
    { width: 375, height: 812 },
  ]) {
    await page.setViewportSize(viewport);
    const initialization = page.locator("[data-studio-initialization]");
    await expect(initialization).toBeFocused();
    const surface = await initialization.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      const background = getComputedStyle(element).backgroundColor;
      return {
        backgroundOpaque: background !== "transparent" && background !== "rgba(0, 0, 0, 0)",
        coversViewport:
          bounds.left <= 0 &&
          bounds.top <= 0 &&
          bounds.right >= globalThis.innerWidth &&
          bounds.bottom >= globalThis.innerHeight,
        fitsWidth: element.scrollWidth <= element.clientWidth,
      };
    });
    expect(surface).toEqual({
      backgroundOpaque: true,
      coversViewport: true,
      fitsWidth: true,
    });
  }
  await page.setViewportSize({ width: 1280, height: 720 });

  const before = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl}/_marimo-studio/status`);
  expect(before).toEqual({
    schema: 1,
    state: "needs-view",
    default_view: "dashboard",
    views: [],
  });

  await page
    .getByLabel("Start with", { exact: true })
    .selectOption("marimo-studio/vanilla:default");
  await page.getByRole("button", { name: "Create dashboard" }).click();
  await expect(page).toHaveURL(`${baseUrl}/studio/dashboard/`);
  await expect(editorSlider(page, /^Hosted scale/)).toHaveAttribute("aria-valuenow", "3");
  await expect(page.getByLabel("Switch view")).toContainText("dashboard");

  const after = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return await response.json();
  }, `${baseUrl}/_marimo-studio/status`);
  expect(after).toEqual({
    schema: 1,
    state: "ready",
    default_view: "dashboard",
    views: ["dashboard"],
  });

  await waitForPreview(page);
  await page.goto(`${baseUrl}/`);
  await expect(page.locator("[data-cell-id]").first()).toBeVisible();
  await page.goto(`${baseUrl}/studio/dashboard/`);
  await expect(editorSlider(page, /^Hosted scale/)).toHaveAttribute("aria-valuenow", "3");
  const preview = await waitForPreview(page);
  const replacement = await readFile(hostedViewFixturePath, "utf8");
  const serverToken = await studioServerToken(page);
  const supersededConfigRead = browserDiagnostics.expectActiveRequestAbort({
    origin: hostedOrigin,
    method: "GET",
    path: /^\/hosted\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/config$/,
    count: 1,
  });
  const abandonedSourceWrite = browserDiagnostics.expectRequestAbort({
    origin: hostedOrigin,
    method: "PUT",
    path: /^\/hosted\/_marimo-studio\/views\/dashboard\/source\/index\.html$/,
    count: 1,
    status: 204,
  });
  const projectResponse = await page.request.get(
    `${baseUrl}/_marimo-studio/views/dashboard/project`,
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
      sourceUrl: `${baseUrl}/_marimo-studio/views/dashboard/source/index.html`,
      token: serverToken,
      viewGeneration: project.view_generation,
    },
  );
  expect(saved).toBe(204);
  await expect(preview.getByRole("heading", { name: "Hosted mount lifecycle" })).toBeVisible();
  const persisted = await page.request.get(
    `${baseUrl}/_marimo-studio/views/dashboard/source/index.html`,
  );
  expect(persisted.ok()).toBe(true);
  expect(await persisted.text()).toBe(replacement);
  await page.getByLabel("Workspace options").click();
  await page.getByRole("button", { name: "Source" }).click();
  await page.getByRole("tab", { name: "index.html" }).click();
  await expect(page.getByLabel("index.html source")).toContainText("Hosted mount lifecycle");
  await expect(
    page
      .getByRole("region", { name: "Source" })
      .getByRole("status", { name: "Source document status" }),
  ).toHaveText("Saved");

  await page.getByRole("button", { name: "Notebook", exact: true }).click();
  await expect(page.locator('iframe[title="Marimo editor"]')).toBeVisible();
  const scale = editorSlider(page, /^Hosted scale/);
  await expect(scale).toBeVisible();
  const value = previewFrame(page).locator('[mo-value="metric"]');
  await scale.press("Home");
  await expect(value).toHaveText("21");
  await scale.press("End");
  await expect(value).toHaveText("63");
  await page.getByRole("button", { name: "Develop", exact: true }).click();
  await waitForPreview(page);
  await expect(preview.getByRole("heading", { name: "Hosted mount lifecycle" })).toBeVisible();
  await expect(value).toHaveText("63");

  await recoverRequestAbort(supersededConfigRead);
  await recoverRequestAbort(abandonedSourceWrite);
  interruptedDocumentTransaction.recovered();
  interruptedDocumentTransactionLog.recovered();
  replacedWorkspaceStream.recovered();
});
