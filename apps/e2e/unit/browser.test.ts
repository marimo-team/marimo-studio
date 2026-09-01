import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { configuredBrowserExecutablePath } from "../scripts/browser.mjs";

test("selects the configured E2E browser executable", () => {
  const executablePath = resolve("/browser/chromium");

  expect(configuredBrowserExecutablePath({ MARIMO_STUDIO_E2E_BROWSER_PATH: executablePath })).toBe(
    executablePath,
  );
  expect(configuredBrowserExecutablePath({})).toBeUndefined();
});
