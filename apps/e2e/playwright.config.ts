import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

import { e2eBrowserUse } from "./scripts/browser.mjs";
import { appDirectory } from "./scripts/paths.mjs";

process.env.MARIMO_STUDIO_E2E_SUITE = "main";

const outputOffset = `offset-${process.env.MARIMO_STUDIO_E2E_PORT_OFFSET ?? "0"}`;

export default defineConfig({
  testDir: "./tests",
  testIgnore: [
    "provider-runtime.spec.ts",
    "provider-reveal.spec.ts",
    "provider-notebook.spec.ts",
    "external-provider.spec.ts",
  ],
  timeout: process.platform === "win32" ? 180_000 : 90_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 1 : 2,
  reporter: process.env.CI
    ? [
        ["list"],
        ["blob", { outputDir: resolve(appDirectory, "test-results/blob-main", outputOffset) }],
      ]
    : "list",
  outputDir: resolve(appDirectory, "test-results/playwright-main", outputOffset),
  expect: { timeout: 15_000 },
  use: {
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], ...e2eBrowserUse },
    },
  ],
});
