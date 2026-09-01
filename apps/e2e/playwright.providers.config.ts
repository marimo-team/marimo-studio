import { defineConfig, devices } from "@playwright/test";

import { e2eBrowserUse } from "./scripts/browser.mjs";
import { e2eNetwork } from "./scripts/network.mjs";
import {
  providerPlaywrightOutputDirectory,
  providerPlaywrightReportDirectory,
} from "./scripts/paths.mjs";

export default defineConfig({
  testDir: "./tests",
  testMatch: ["provider-runtime.spec.ts", "provider-reveal.spec.ts", "external-provider.spec.ts"],
  timeout: 180_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: providerPlaywrightReportDirectory }]]
    : "list",
  outputDir: providerPlaywrightOutputDirectory,
  expect: { timeout: 65_000 },
  use: {
    baseURL: e2eNetwork.provider.live.origin,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "provider-chromium",
      use: { ...devices["Desktop Chrome"], ...e2eBrowserUse },
    },
  ],
  webServer: {
    command: "node scripts/serve-providers.mjs",
    url: `${e2eNetwork.provider.live.origin}/_marimo-studio/status`,
    reuseExistingServer: false,
    timeout: 420_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 60_000 },
    stdout: "pipe",
    stderr: "pipe",
  },
});
