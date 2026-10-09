import { expect } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { editorSlider, selectWorkspaceMode, waitForPreview } from "./fixture.ts";
import { test } from "./provider-fixture.ts";

// `marimo edit` serves the provider notebook beneath a random /s/<id>/p/<id>/
// prefix that the proxy strips before forwarding.
test.use({ providerViews: ["paper"], providerEditor: true });

test("renders a LaTeX document again when a notebook value changes", async ({ page }) => {
  test.setTimeout(240_000);
  const endpoint = e2eNetwork.provider.proxiedEdit;
  const diagnostics = observeBrowserContext(page.context());
  try {
    await page.goto(`${endpoint.publicUrl}/studio/paper/`);
    const viewer = (await waitForPreview(page)).locator("marimo-document");
    await expect(viewer.locator(".textLayer")).toContainText("Metric is 42");
    await expect(viewer).toHaveAttribute("data-state", "ready");

    await selectWorkspaceMode(page, "Notebook");
    await editorSlider(page).press("End");
    await selectWorkspaceMode(page, "Develop");
    await waitForPreview(page);
    await expect(viewer.locator(".textLayer")).toContainText("Metric is 63");
    await expect(viewer).toHaveAttribute("data-state", "ready");
    expect(endpoint.escapedRequests()).toEqual([]);
  } finally {
    await diagnostics.close();
  }
  expect(diagnostics.messages).toEqual([]);
});
