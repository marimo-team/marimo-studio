import { expect } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.mjs";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { labeledSlider } from "./fixture.ts";
import { test } from "./provider-fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

test.use({ providerViews: ["slides"] });

test("the React Reveal starter runs as a narrow static WebAssembly deck", async ({
  context,
  page,
}) => {
  test.setTimeout(180_000);
  const diagnostics = observeBrowserContext(context);
  try {
    await installPinnedPyodideAssets(context);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${e2eNetwork.provider.reveal.origin}/`);
    const root = page.locator("html");

    await expect
      .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
        timeout: 65_000,
      })
      .toBe(true);
    await root.evaluate(() => globalThis.marimoStudio.ready());
    await expect(root.getByRole("heading", { name: "Projections", level: 1 })).toBeVisible();

    await root.getByRole("button", { name: "next slide" }).click();
    await expect(root.getByRole("heading", { name: "Controls" })).toBeVisible();
    const scale = labeledSlider(root.locator('marimo-cell[name="controls"]'), /^Scale/);
    await expect(scale).toBeVisible();
    await scale.press("Home");
    await expect(scale).toHaveAttribute("aria-valuenow", "1");
    await expect(root.getByRole("heading", { name: "Controls" })).toBeVisible();
    await root.getByRole("button", { name: "next slide" }).click();
    await expect(root.getByRole("heading", { name: "Metric" })).toBeVisible();
    await expect(root.locator('marimo-cell[name="metric"]')).toHaveText("21");
    await page.keyboard.press("ArrowLeft");
    await expect(root.getByRole("heading", { name: "Controls" })).toBeVisible();
    await page.keyboard.press("ArrowRight");
    await expect(root.getByRole("heading", { name: "Metric" })).toBeVisible();
    expect(
      await root.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
  } finally {
    await diagnostics.close();
    expect(diagnostics.messages).toEqual([]);
  }
});
