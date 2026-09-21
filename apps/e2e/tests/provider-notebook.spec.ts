import { expect } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { labeledSlider, presentationFrame, recoverRequestAbort } from "./fixture.ts";
import { test } from "./provider-fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

test.use({ providerViews: ["notebook"] });

for (const runtime of ["Server", "static WebAssembly", "Prepared"] as const) {
  test(`Notebook Kit retains native projections through Observable reactivity in ${runtime}`, async ({
    context,
    page,
  }, testInfo) => {
    const diagnostics = observeBrowserContext(context);
    try {
      const pythonRequests: string[] = [];
      const remoteTemplateRequests: string[] = [];
      context.on("request", (request) => {
        if (/pyodide|\.whl(?:$|\?)/i.test(request.url())) pythonRequests.push(request.url());
        if (/\/npm\/htl(?:@|\/)/.test(request.url())) remoteTemplateRequests.push(request.url());
      });
      if (runtime === "static WebAssembly") {
        await installPinnedPyodideAssets(context);
      }
      const urls = {
        Server: `${e2eNetwork.provider.live.origin}/notebook/`,
        "static WebAssembly": `${e2eNetwork.provider.notebook.origin}/`,
        Prepared: `${e2eNetwork.provider.notebookPrepared.origin}/`,
      };
      await page.goto(urls[runtime]);
      const root =
        runtime === "Server" ? presentationFrame(page).locator("html") : page.locator("html");
      await expect(root.getByRole("heading", { name: "Notebook Kit projections" })).toBeVisible();
      await expect(root.getByText("Attached total: 21", { exact: true })).toBeVisible();
      await expect(root.locator("#observable-metric")).toHaveText("Observable metric: 42");
      const scale = labeledSlider(root.locator('marimo-cell[name="controls"]'), /^Scale/);
      const results = root.getByRole("region", { name: "Reactive results" });
      for (const [key, value] of [
        ["Home", 21],
        ["End", 63],
        ["Home", 21],
      ] as const) {
        await scale.press(key);
        await expect(root.locator("#observable-metric")).toHaveText(`Observable metric: ${value}`);
        await expect(results.locator('marimo-cell[name="metric"]')).toHaveText(String(value));
        await expect(results.locator("#late-scale")).toHaveText(String(value / 21));
      }
      const output = root.getByRole("region", { name: "Selected output" });
      for (const [selection, heading] of [
        ["first", "First projected result"],
        ["second", "Second projected result"],
        ["first", "First projected result"],
      ] as const) {
        await root.getByLabel("Projected result").selectOption(selection);
        await expect(output.getByRole("heading")).toHaveText([heading]);
        await expect(output.getByRole("heading")).toBeVisible();
      }
      await page.setViewportSize({ width: 390, height: 844 });
      expect(
        await root.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath("notebook-kit-narrow.png"),
        fullPage: true,
      });
      await scale.press("ArrowRight");
      await expect(root.locator("#observable-metric")).toHaveText("Observable metric: 42");
      await expect(results.locator('marimo-cell[name="metric"]')).toHaveText("42");
      await expect(results.locator("#late-scale")).toHaveText("2");
      const projectionFailure = diagnostics.expectConsole({
        type: "error",
        text: /Projected metric unavailable/,
      });
      await root.locator('[mo-value="metric"]').evaluate((host) => {
        host.dispatchEvent(
          new CustomEvent("marimo-value-error", {
            detail: {
              selector: "metric",
              code: "value-unavailable",
              message: "Projected metric unavailable",
            },
          }),
        );
      });
      await expect(root.locator("#cell-4").getByText("Projected metric unavailable")).toBeVisible();
      const frameElement =
        runtime === "Server"
          ? await page.locator("iframe#marimo-studio-presentation").elementHandle()
          : null;
      const retiringFrame = await frameElement?.contentFrame();
      await frameElement?.dispose();
      const retirement = retiringFrame
        ? diagnostics.expectFrameRetirement(retiringFrame)
        : undefined;
      const retiringValues =
        runtime === "Server"
          ? diagnostics.expectActiveRequestAbort({
              origin: e2eNetwork.provider.live.origin,
              method: "GET",
              path: /\/_marimo-studio\/views\/notebook\/values$/,
              required: false,
            })
          : undefined;
      await page.reload();
      await expect(root.locator("#observable-metric")).toHaveText("Observable metric: 42");
      if (retiringValues) await recoverRequestAbort(retiringValues);
      retirement?.recovered();
      projectionFailure.recovered();
      if (runtime === "Prepared") expect(pythonRequests).toEqual([]);
      expect(remoteTemplateRequests).toEqual([]);
    } finally {
      await diagnostics.close();
      expect(diagnostics.messages).toEqual([]);
    }
  });
}
