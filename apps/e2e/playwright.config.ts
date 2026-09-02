import { defineConfig, devices } from "@playwright/test";

import { e2eBrowserUse } from "./scripts/browser.mjs";
import { e2eNetwork } from "./scripts/network.mjs";
import { mainPlaywrightOutputDirectory, mainPlaywrightReportDirectory } from "./scripts/paths.mjs";

export default defineConfig({
  testDir: "./tests",
  testIgnore: ["provider-runtime.spec.ts", "provider-reveal.spec.ts", "external-provider.spec.ts"],
  timeout: process.platform === "win32" ? 180_000 : 90_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: mainPlaywrightReportDirectory }]]
    : "list",
  outputDir: mainPlaywrightOutputDirectory,
  expect: { timeout: 15_000 },
  use: {
    baseURL: e2eNetwork.main.studio.origin,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], ...e2eBrowserUse },
    },
  ],
  webServer: {
    command: "node scripts/serve.mjs",
    url: `${e2eNetwork.main.studio.origin}/`,
    reuseExistingServer: false,
    timeout: 180_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
    stdout: "pipe",
    stderr: "pipe",
  },
});
