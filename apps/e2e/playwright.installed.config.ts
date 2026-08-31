import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

import { e2eBrowserUse } from "./scripts/browser.mjs";
import { installedPackageNetwork } from "./scripts/installed-package-network.mjs";

const installedWheel = process.env.MARIMO_STUDIO_E2E_WHEEL;
const outputRoot = process.env.MARIMO_STUDIO_E2E_INSTALLED_OUTPUT_ROOT;
if (!installedWheel || !outputRoot) {
  throw new Error("Run the installed-wheel acceptance through pnpm e2e:installed");
}

export default defineConfig({
  testDir: "./installed-tests",
  testMatch: "installed-wheel.spec.ts",
  timeout: 90_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: process.env.CI
    ? [
        ["list"],
        [
          "html",
          {
            open: "never",
            outputFolder: resolve(outputRoot, "report"),
          },
        ],
      ]
    : "list",
  outputDir: resolve(outputRoot, "playwright"),
  expect: { timeout: 65_000 },
  use: {
    baseURL: installedPackageNetwork.origin,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "installed-wheel-chromium",
      use: { ...devices["Desktop Chrome"], ...e2eBrowserUse },
    },
  ],
  webServer: {
    command: "node scripts/serve-installed-package.mjs",
    env: { ...process.env, MARIMO_STUDIO_E2E_WHEEL: installedWheel },
    url: `${installedPackageNetwork.origin}/_marimo-studio/status`,
    reuseExistingServer: false,
    timeout: 240_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 15_000 },
    stdout: "pipe",
    stderr: "pipe",
  },
});
