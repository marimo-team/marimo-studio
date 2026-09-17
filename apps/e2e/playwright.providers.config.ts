import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

import { e2eBrowserUse } from "./scripts/browser.mjs";
import { appDirectory } from "./scripts/paths.mjs";

process.env.MARIMO_STUDIO_E2E_SUITE = "provider";

const outputOffset = `offset-${process.env.MARIMO_STUDIO_E2E_PORT_OFFSET ?? "0"}`;

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
  reporter: process.env.CI
    ? [
        ["list"],
        ["blob", { outputDir: resolve(appDirectory, "test-results/blob-provider", outputOffset) }],
      ]
    : "list",
  outputDir: resolve(appDirectory, "test-results/playwright-provider", outputOffset),
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
