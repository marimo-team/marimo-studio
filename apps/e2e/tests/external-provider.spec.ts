import { expect, test } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.mjs";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { presentationFrame } from "./fixture.ts";

test("an installed external provider creates, builds, and serves its view", async ({ page }) => {
  const diagnostics = observeBrowserContext(page.context());

  await page.goto(`${e2eNetwork.provider.external.origin}/`);
  const root = presentationFrame(page).locator("html");

  await expect(root.locator("[data-external-provider]")).toHaveText("Dashboard");
  await expect(root.locator("[data-external-value]")).toHaveText("External provider acceptance");
  await expect
    .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
      timeout: 65_000,
    })
    .toBe(true);
  await root.evaluate(() => globalThis.marimoStudio.ready());
  await diagnostics.close();
  expect(diagnostics.messages).toEqual([]);
});
