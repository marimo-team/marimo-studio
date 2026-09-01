import { expect, test, type Locator } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.mjs";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { presentationFrame } from "./fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

const waitForRuntime = async (root: Locator): Promise<void> => {
  await expect
    .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
      timeout: 65_000,
    })
    .toBe(true);
  await root.evaluate(() => globalThis.marimoStudio.ready());
};

const expectWebProject = async (root: Locator): Promise<void> => {
  await waitForRuntime(root);
  await expect(root.getByRole("heading", { name: "External web project" })).toHaveCSS(
    "color",
    "rgb(24, 78, 55)",
  );
  await expect(root.locator("[data-web-script]")).toHaveText("Imported module ready");
  await expect(root.locator("[data-web-value]")).toHaveText("42");
};

test("an installed external provider creates, builds, and serves its view", async ({ page }) => {
  const diagnostics = observeBrowserContext(page.context());
  try {
    await page.goto(`${e2eNetwork.provider.external.origin}/`);
    const root = presentationFrame(page).locator("html");

    await expect(root.locator("[data-external-provider]")).toHaveText("Dashboard");
    await expect(root.locator("[data-external-value]")).toHaveText("External provider acceptance");
    await waitForRuntime(root);
  } finally {
    await diagnostics.close();
    expect(diagnostics.messages).toEqual([]);
  }
});

test("an installed multi-file provider serves its local CSS and imported JavaScript", async ({
  page,
}) => {
  const diagnostics = observeBrowserContext(page.context());
  try {
    await page.goto(`${e2eNetwork.provider.live.origin}/web/`);
    await expectWebProject(presentationFrame(page).locator("html"));
  } finally {
    await diagnostics.close();
    expect(diagnostics.messages).toEqual([]);
  }
});

test("an installed multi-file provider preserves local browser assets in static WebAssembly", async ({
  context,
  page,
}) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await installPinnedPyodideAssets(context);
    await page.goto(`${e2eNetwork.provider.web.origin}/src/index.html`);
    await expectWebProject(page.locator("html"));
  } finally {
    await diagnostics.close();
    expect(diagnostics.messages).toEqual([]);
  }
});
