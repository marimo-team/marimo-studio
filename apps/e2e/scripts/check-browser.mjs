import { access } from "node:fs/promises";

try {
  const { chromium } = await import("@playwright/test");
  await access(chromium.executablePath());
} catch {
  process.stderr.write("Chromium for Playwright is unavailable. Run 'make setup' to install it.\n");
  process.exitCode = 1;
}
