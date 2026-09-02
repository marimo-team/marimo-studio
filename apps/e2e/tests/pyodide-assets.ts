import type { BrowserContext } from "@playwright/test";

import { access, readdir, realpath } from "node:fs/promises";
import { basename, join, resolve } from "node:path";

import { repositoryDirectory } from "../scripts/paths.mjs";

export const PYODIDE_VERSION = "314.0.0";
export const PYODIDE_CDN_ROOT = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

const preparedPnpmDirectory = resolve(
  repositoryDirectory,
  "packages/marimo-frontend/.cache/marimo/node_modules/.pnpm",
);

let preparedDirectory: Promise<string> | undefined;

const findPreparedPyodideDirectory = async (): Promise<string> => {
  const candidates: string[] = [];
  for (const entry of await readdir(preparedPnpmDirectory, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith("pyodide@")) {
      continue;
    }
    const candidate = join(preparedPnpmDirectory, entry.name, "node_modules/pyodide");
    if (
      await access(candidate)
        .then(() => true)
        .catch(() => false)
    ) {
      candidates.push(await realpath(candidate));
    }
  }
  if (candidates.length !== 1) {
    throw new Error(`Expected one prepared Pyodide package, found ${candidates.length}`);
  }
  return candidates[0];
};

const preparedPyodideDirectory = (): Promise<string> =>
  (preparedDirectory ??= findPreparedPyodideDirectory());

const contentType = (file: string): string => {
  if (file.endsWith(".wasm")) return "application/wasm";
  if (file.endsWith(".json") || file.endsWith(".map")) return "application/json";
  if (file.endsWith(".zip")) return "application/zip";
  return file.endsWith(".js") || file.endsWith(".mjs")
    ? "text/javascript; charset=utf-8"
    : "application/octet-stream";
};

export const installPinnedPyodideAssets = async (context: BrowserContext): Promise<void> => {
  const directory = await preparedPyodideDirectory();
  await context.route(`${PYODIDE_CDN_ROOT}**`, async (route) => {
    const file = basename(new URL(route.request().url()).pathname);
    const local = join(directory, file);
    if (
      file &&
      (await access(local)
        .then(() => true)
        .catch(() => false))
    ) {
      await route.fulfill({ path: local, contentType: contentType(file) });
      return;
    }
    await route.continue();
  });
};
