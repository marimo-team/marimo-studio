import { expect, test as base } from "@playwright/test";

import { readInstalledPackageNetwork } from "../scripts/installed-package-network.ts";

const installedPackageNetwork = readInstalledPackageNetwork();
import { expectFirstSaveRetirement } from "../tests/authoring-test-support.ts";
import { observeBrowserContext } from "../tests/browser-diagnostics.ts";
import { installPinnedPyodideAssets } from "../tests/pyodide-assets.ts";

const test = base.extend<{ diagnostics: ReturnType<typeof observeBrowserContext> }>({
  diagnostics: [
    async ({ context }, use, testInfo) => {
      const diagnostics = observeBrowserContext(context);
      try {
        await use(diagnostics);
      } finally {
        await diagnostics.close();
        if (diagnostics.messages.length > 0 || testInfo.status !== testInfo.expectedStatus) {
          await testInfo.attach("browser-diagnostics", {
            body: Buffer.from(diagnostics.messages.join("\n") || "No browser errors recorded."),
            contentType: "text/plain",
          });
        }
        expect(diagnostics.messages, "unexpected browser diagnostics").toEqual([]);
      }
    },
    { auto: true },
  ],
});

test("runs prepared controls and widgets with atomic state replacement from the installed wheel", async ({
  page,
  diagnostics,
}) => {
  const requests: string[] = [];
  const workers: string[] = [];
  const sockets: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("worker", (worker) => workers.push(worker.url()));
  page.on("websocket", (socket) => sockets.push(socket.url()));
  await page.goto(`${installedPackageNetwork.static.origin}/prepared/`);
  await expect
    .poll(() => page.evaluate(() => globalThis.marimoStudio?.state !== undefined))
    .toBe(true);
  await page.evaluate(() => globalThis.marimoStudio.ready());
  await expect(page.locator("#projected-answer")).toHaveText("42");
  await expect(page.getByRole("heading", { name: "Prepared total: 42" })).toBeVisible();
  await page.getByRole("button", { name: "Widget count: 7" }).click();
  await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

  const slider = page.locator('marimo-cell[name="controls"] marimo-slider').getByRole("slider");
  await slider.press("Home");
  await expect(page.locator("#projected-answer")).toHaveText("21");
  await expect(page.getByRole("heading", { name: "Prepared total: 21" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

  await page.evaluate(async () => {
    const state = globalThis.marimoStudio.state!;
    await Promise.allSettled([state.update({ scale: 2 }), state.update({ scale: 1 })]);
  });
  await expect(page.locator("#projected-answer")).toHaveText("21");
  expect(await page.evaluate(() => globalThis.marimoStudio.state!.inputs())).toEqual({
    scale: 1,
  });

  let failedUrl: string | undefined;
  const responseFailure = diagnostics.expectResponse({ status: 503, path: /.*/ });
  const cancelledReplacement = diagnostics.expectRequestAbort({
    origin: installedPackageNetwork.static.origin,
    method: "GET",
    path: /^\/prepared\/_marimo-studio\/views\/dashboard\/zero-python\/[a-f\d]+\/assets\/[a-f\d]+\.(?:output|cell)\.json$/,
    count: 3,
    required: false,
  });
  await page.route(`${installedPackageNetwork.static.origin}/**`, async (route) => {
    if (failedUrl === undefined) {
      failedUrl = route.request().url();
      await route.fulfill({ status: 503, body: "Prepared output unavailable" });
    } else {
      await route.continue();
    }
  });
  await expect(
    page.evaluate(() => globalThis.marimoStudio.state!.update({ scale: 3 })),
  ).rejects.toThrow();
  cancelledReplacement.seal();
  await expect.poll(() => cancelledReplacement.ready()).toBe(true);
  expect(failedUrl).toBeDefined();
  await expect(page.locator("#projected-answer")).toHaveText("21");
  await expect(page.getByRole("heading", { name: "Prepared total: 21" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
  expect(await page.evaluate(() => globalThis.marimoStudio.state!.inputs())).toEqual({
    scale: 1,
  });

  await page.unroute(`${installedPackageNetwork.static.origin}/**`);
  await page.evaluate(() => globalThis.marimoStudio.state!.update({ scale: 3 }));
  await expect(page.locator("#projected-answer")).toHaveText("63");
  await expect(page.getByRole("heading", { name: "Prepared total: 63" })).toBeVisible();
  expect(cancelledReplacement.recovered()).toBe(true);
  responseFailure.recovered();
  await page.setViewportSize({ width: 390, height: 844 });

  await expect(
    page.evaluate(() => globalThis.marimoStudio.state!.update({ scale: 99 })),
  ).rejects.toThrow();
  expect(await page.evaluate(() => globalThis.marimoStudio.state!.inputs())).toEqual({
    scale: 3,
  });
  await expect(page.locator("#projected-answer")).toHaveText("63");
  await expect(page.getByRole("heading", { name: "Prepared total: 63" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
  await slider.press("Home");
  await expect(page.locator("#projected-answer")).toHaveText("21");
  expect(workers).toEqual([]);
  expect(sockets).toEqual([]);
  expect(requests.filter((url) => /pyodide|\.whl(?:\?|$)|\.py(?:\?|$)/i.test(url))).toEqual([]);
});

test("renders a projected value in run mode from the installed wheel", async ({ page }) => {
  await page.goto(installedPackageNetwork.run.origin);
  const presentation = page.frameLocator("iframe#marimo-studio-presentation");

  await expect(presentation.getByRole("heading", { name: "Installed wheel smoke" })).toBeVisible();
  await expect(presentation.locator("#projected-answer")).toHaveText("42");
});

test("opens the first view and captures Lens feedback from the installed extra", async ({
  page,
}) => {
  await page.goto("/?file=notebook.py");
  await expect(page).toHaveURL(/\/studio\/dashboard\/$/);
  await expect(page.getByRole("button", { name: "Show view beside notebook" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Toggle Source editor" }).click();
  await expect(page.getByRole("tab", { name: "index.html" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const presentation = page.frameLocator('iframe[data-preview-runtime-frame="server"]');
  await expect(presentation.getByRole("heading", { name: "Installed wheel smoke" })).toBeVisible();
  await presentation.getByRole("button", { name: "Select a target", exact: true }).click();
  await presentation.locator("#projected-answer").click();
  const editor = presentation.getByRole("dialog", { name: /Add note for/ });
  await editor.getByRole("textbox").fill("Explain this projected answer");
  await editor.getByRole("button", { name: "Done", exact: true }).click();
  await presentation.getByRole("button", { name: "Open selections, 1 open, 0 in history" }).click();
  await expect(presentation.getByRole("button", { name: /Current selection S1,/ })).toContainText(
    "Explain this projected answer",
  );
  await presentation.getByRole("button", { name: "View image for S1.", exact: true }).click();
  const image = presentation
    .getByRole("dialog", { name: "Selection image for S1" })
    .getByRole("img");
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBeGreaterThan(0);
});

test("runs an interactive static export from the installed wheel", async ({ context, page }) => {
  await installPinnedPyodideAssets(context);
  await page.goto(installedPackageNetwork.static.origin);
  await expect
    .poll(() => page.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
      timeout: 65_000,
    })
    .toBe(true);
  await page.evaluate(() => globalThis.marimoStudio.ready());

  await expect(page.getByRole("heading", { name: "Installed wheel smoke" })).toBeVisible();
  await expect(page.locator("#projected-answer")).toHaveText("42");
  await page
    .locator('marimo-cell[name="controls"]')
    .locator("marimo-slider")
    .getByRole("slider")
    .press("End");
  await expect(page.locator("#projected-answer")).toHaveText("63");
});

test("provides Studio before the first save in an environment with the installed wheel", async ({
  page,
  diagnostics,
}) => {
  const fallback = diagnostics.expectConsole({
    type: "warning",
    text: /^No filename provided, using fallback$/,
    required: false,
  });
  const description = diagnostics.expectConsole({
    type: "warning",
    text: /Missing `Description` or `aria-describedby/,
    required: false,
  });
  const instantiated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
      response.ok(),
  );
  await page.goto(installedPackageNetwork.fresh.origin);
  const initialSession = (await instantiated).request().headers()["marimo-session-id"];
  expect(initialSession).toBeTruthy();
  const add = page.getByRole("button", { name: "+ Add view", exact: true });
  await expect(add).toBeVisible();
  await expect(page.locator("[data-cell-id]").first()).toBeVisible();
  // A new notebook focuses its first cell after the initial run. Opening the
  // save dialog before that focus change would clear the typed filename.
  await expect(page.locator("[data-cell-id] .cm-content").first()).toBeFocused();
  await add.click();
  const saveDialog = page.getByRole("dialog", { name: "Save notebook" });
  await expect(saveDialog).toBeVisible();
  const save = saveDialog.getByText("Save as: fresh-studio.py", { exact: true });
  await expect(async () => {
    await saveDialog.getByPlaceholder("filename").fill("fresh-studio.py");
    await expect(save).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 65_000 });
  // First save navigates into Studio and may retire the original POST response.
  // The saved document and preserved session are the completion evidence.
  const retiredSave = expectFirstSaveRetirement(diagnostics, installedPackageNetwork.fresh.origin);
  const saved = page.waitForURL((url) => url.searchParams.get("file") === "fresh-studio.py");
  await Promise.all([save.click(), saved]);
  const editor = page.frameLocator("iframe#marimo-studio-editor");
  await expect(editor.locator("[data-cell-id]").first()).toBeVisible();
  const editorUrl = await page.locator("iframe#marimo-studio-editor").getAttribute("src");
  const savedEditor = new URL(editorUrl!, page.url());
  expect(savedEditor.searchParams.get("file")).toBe("fresh-studio.py");
  expect(savedEditor.searchParams.get("session_id")).toBe(initialSession);
  retiredSave.recovered();
  await page.getByText("Add view", { exact: true }).click();
  await page.getByRole("radio", { name: /^HTML document/ }).check();
  const replaced = diagnostics.expectWorkspaceEventStreamReplacement(
    new URL("/_marimo-studio/dev/events", installedPackageNetwork.fresh.origin).href,
    1,
  );
  await page.getByRole("button", { name: "Create view", exact: true }).click();
  await expect(page.getByRole("button", { name: "Show view beside notebook" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const preview = page.frameLocator('iframe[data-preview-runtime-frame="server"]');
  await expect(preview.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  fallback.recovered();
  description.recovered();
  replaced.recovered();
});
