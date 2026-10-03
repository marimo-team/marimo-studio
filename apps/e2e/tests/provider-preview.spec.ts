import { expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { e2eNetwork } from "../scripts/network.ts";
import { providerNotebookPath, providerWorkspaceDirectory } from "../scripts/paths.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { expectPreviewRevisionSwap, labeledSlider, waitForPreview } from "./fixture.ts";
import { test } from "./provider-fixture.ts";
import { StudioCli } from "./studio-cli.ts";

// `marimo edit` serves the provider notebook beneath a random /s/<id>/p/<id>/
// prefix that the proxy strips before forwarding.
test.use({ providerViews: ["gallery"], providerEditor: true });

const appSource = resolve(
  providerWorkspaceDirectory,
  "__marimo__/studio/projections/gallery/src/App.tsx",
);

test("keeps a React view's preview URL live beneath a stripped proxy prefix", async ({ page }) => {
  test.setTimeout(240_000);
  const endpoint = e2eNetwork.provider.proxiedEdit;
  const root = `${endpoint.publicUrl}/`;
  const diagnostics = observeBrowserContext(page.context());
  const cli = new StudioCli();
  const original = await readFile(appSource, "utf8");
  try {
    await page.goto(`${root}studio/gallery/`);
    await waitForPreview(page);

    const url = await cli.previewView(providerNotebookPath, root, "gallery", "server");

    expect(url.startsWith(`${root}gallery/?`)).toBe(true);
    const tab = await page.context().newPage();
    await tab.goto(url);
    await expect(tab.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
      timeout: 120_000,
    });
    await expect(tab.getByRole("heading", { name: "Gallery", exact: true })).toBeVisible();
    const viewPath = new URL(`${root}gallery/`).pathname;

    const revisionSwap = expectPreviewRevisionSwap(diagnostics, root, "gallery");
    await writeFile(
      appSource,
      original.replace('const VIEW_HEADING = "Gallery";', 'const VIEW_HEADING = "Agent gallery";'),
    );

    await expect(tab.getByRole("heading", { name: "Agent gallery" })).toBeVisible({
      timeout: 120_000,
    });
    expect(new URL(tab.url()).pathname).toBe(viewPath);
    await labeledSlider(tab.locator("body"), /^Scale/).press("End");
    await tab.close();
    await revisionSwap();
    expect(endpoint.escapedRequests()).toEqual([]);
  } finally {
    await writeFile(appSource, original);
    await cli.close();
    await diagnostics.close();
  }
  expect(diagnostics.messages).toEqual([]);
});
