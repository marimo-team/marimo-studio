import { expect } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { labeledSlider, presentationFrame } from "./fixture.ts";
import { test } from "./provider-fixture.ts";

test.use({ providerViews: ["article"] });

test("a Quarto view runs notebook cells inside Quarto's page", async ({ context, page }) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await page.goto(`${e2eNetwork.provider.live.origin}/article/`);
    const root = presentationFrame(page).locator("html");
    await expect
      .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
        timeout: 65_000,
      })
      .toBe(true);
    await root.evaluate(() => globalThis.marimoStudio.ready());

    await expect(root.locator("#title-block-header h1")).toHaveText("Article");
    const metric = root.locator('#app-shell marimo-cell[name="metric"]');
    await expect(metric).toHaveText("42");
    const scale = labeledSlider(root.locator('marimo-cell[name="controls"]'), /^Scale/);
    await scale.press("End");
    await expect(metric).toHaveText("63");
  } finally {
    await diagnostics.close();
    expect(diagnostics.messages).toEqual([]);
  }
});
