import { expect, test } from "@playwright/test";

import { installedPackageNetwork } from "../scripts/installed-package-network.mjs";
import { observeBrowserContext } from "../tests/browser-diagnostics.ts";
import { installPinnedPyodideAssets } from "../tests/pyodide-assets.ts";

test("runs prepared controls and widgets with atomic state replacement from the installed wheel", async ({
  context,
  page,
}, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  const requests: string[] = [];
  const workers: string[] = [];
  const sockets: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("worker", (worker) => workers.push(worker.url()));
  page.on("websocket", (socket) => sockets.push(socket.url()));
  try {
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
    const rejected = await page.evaluate(async () => {
      try {
        await globalThis.marimoStudio.state!.update({ scale: 3 });
        return false;
      } catch {
        return true;
      }
    });
    expect(rejected).toBe(true);
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
    expect(workers).toEqual([]);
    expect(sockets).toEqual([]);
    expect(requests.filter((url) => /pyodide|\.whl(?:\?|$)|\.py(?:\?|$)/i.test(url))).toEqual([]);
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
});

test("rejects an unprepared input while retaining the current native presentation", async ({
  context,
  page,
}, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await page.goto(`${installedPackageNetwork.static.origin}/prepared/`);
    await expect
      .poll(() => page.evaluate(() => globalThis.marimoStudio?.state !== undefined))
      .toBe(true);
    await page.evaluate(() => globalThis.marimoStudio.ready());
    await page.getByRole("button", { name: "Widget count: 7" }).click();
    await page.evaluate(() => globalThis.marimoStudio.state!.update({ scale: 3 }));
    await expect(page.locator("#projected-answer")).toHaveText("63");
    await page.setViewportSize({ width: 390, height: 844 });

    const rejected = await page.evaluate(async () => {
      try {
        await globalThis.marimoStudio.state!.update({ scale: 99 });
        return false;
      } catch {
        return true;
      }
    });

    expect(rejected).toBe(true);
    expect(await page.evaluate(() => globalThis.marimoStudio.state!.inputs())).toEqual({
      scale: 3,
    });
    await expect(page.locator("#projected-answer")).toHaveText("63");
    await expect(page.getByRole("heading", { name: "Prepared total: 63" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    await page
      .locator('marimo-cell[name="controls"] marimo-slider')
      .getByRole("slider")
      .press("Home");
    await expect(page.locator("#projected-answer")).toHaveText("21");
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
});

test("renders a projected value in run mode from the installed wheel", async ({
  context,
  page,
}, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await page.goto(installedPackageNetwork.run.origin);
    const presentation = page.frameLocator("iframe#marimo-studio-presentation");

    await expect(
      presentation.getByRole("heading", { name: "Installed wheel smoke" }),
    ).toBeVisible();
    await expect(presentation.locator("#projected-answer")).toHaveText("42");
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
});

test("opens the first view in edit mode from the installed wheel", async ({
  context,
  page,
}, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await page.goto("/?file=notebook.py");
    await expect(page).toHaveURL(/\/studio\/dashboard\/$/);
    await expect(page.getByRole("button", { name: "Develop" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByRole("tab", { name: "index.html" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const presentation = page.frameLocator('iframe[data-preview-runtime-frame="server"]');
    await expect(
      presentation.getByRole("heading", { name: "Installed wheel smoke" }),
    ).toBeVisible();
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
});

test("runs an interactive static export from the installed wheel", async ({
  context,
  page,
}, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  try {
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
});
