import { expect, test } from "@playwright/test";

import { installedPackageNetwork } from "../scripts/installed-package-network.mjs";
import { observeBrowserContext } from "../tests/browser-diagnostics.ts";
import { installPinnedPyodideAssets } from "../tests/pyodide-assets.ts";

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
    const presentation = page.frameLocator('iframe[data-preview-runtime-frame="server"]');
    await expect
      .poll(() =>
        presentation
          .locator("html")
          .evaluate(() => globalThis.marimoStudio !== undefined)
          .catch(() => false),
      )
      .toBe(true);
    await presentation.locator("html").evaluate(() => globalThis.marimoStudio.ready());

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
