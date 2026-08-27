import { expect, test } from "@playwright/test";

import { observeBrowserContext } from "../tests/browser-diagnostics.ts";

test("renders a projected value from the installed wheel", async ({ context, page }, testInfo) => {
  const diagnostics = observeBrowserContext(context);
  try {
    await page.goto("/");
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
