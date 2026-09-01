import { isAbsolute } from "node:path";

export const configuredBrowserExecutablePath = (environment = process.env) => {
  const executablePath = environment.MARIMO_STUDIO_E2E_BROWSER_PATH;

  if (
    executablePath !== undefined &&
    (!executablePath || executablePath.trim() !== executablePath || !isAbsolute(executablePath))
  ) {
    throw new TypeError("MARIMO_STUDIO_E2E_BROWSER_PATH must be a non-empty absolute path");
  }

  return executablePath;
};

const executablePath = configuredBrowserExecutablePath();

export const e2eBrowserUse = executablePath
  ? Object.freeze({ launchOptions: Object.freeze({ executablePath }) })
  : Object.freeze({});
