import { access } from "node:fs/promises";

import { configuredBrowserExecutablePath } from "./browser.ts";

try {
  const { chromium } = await import("@playwright/test");
  await access(configuredBrowserExecutablePath() ?? chromium.executablePath());
} catch {
  process.stderr.write("Chromium for Playwright is unavailable. Run 'make setup' to install it.\n");
  process.exitCode = 1;
}
