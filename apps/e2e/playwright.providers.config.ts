import { defineConfig, devices } from "@playwright/test";

import { e2eBrowserUse } from "./scripts/browser.mjs";

process.env.MARIMO_STUDIO_E2E_SUITE = "provider";
const { blobReportDirectory, playwrightOutputDirectory } = await import("./scripts/paths.mjs");

export default defineConfig({
  testDir: "./tests",
  testMatch: [
    "provider-runtime.spec.ts",
    "provider-reveal.spec.ts",
    "provider-notebook.spec.ts",
    "external-provider.spec.ts",
  ],
  timeout: 180_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["blob", { outputDir: blobReportDirectory }]] : "list",
  outputDir: playwrightOutputDirectory,
  expect: { timeout: 65_000 },
  use: {
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "provider-chromium",
      use: { ...devices["Desktop Chrome"], ...e2eBrowserUse },
    },
  ],
});
