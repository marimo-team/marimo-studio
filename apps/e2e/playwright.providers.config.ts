import { defineConfig, devices } from "@playwright/test";
import { availableParallelism } from "node:os";

import { e2eBrowserUse } from "./scripts/browser.ts";

process.env.MARIMO_STUDIO_E2E_SUITE = "provider";
const { blobReportDirectory, playwrightOutputDirectory } = await import("./scripts/paths.ts");

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
  workers: process.env.CI ? 1 : Math.min(2, availableParallelism()),
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
