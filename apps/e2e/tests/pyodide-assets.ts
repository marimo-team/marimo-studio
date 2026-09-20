import type { BrowserContext, Request, Route } from "@playwright/test";

import { basename, join } from "node:path";

import {
  PYODIDE_CDN_ROOT,
  pyodidePayloadDirectory,
  verifyPyodidePayload,
} from "../scripts/prepare-pyodide.ts";

export { PYODIDE_CDN_ROOT, PYODIDE_VERSION } from "../scripts/prepare-pyodide.ts";

type AssetHandler = (
  route: Pick<Route, "fulfill" | "continue">,
  request: Pick<Request, "url">,
) => Promise<void>;

interface PyodideAssetContext {
  route(url: string, handler: AssetHandler): ReturnType<BrowserContext["route"]>;
}

let preparedPayload: ReturnType<typeof verifyPyodidePayload> | undefined;

const contentType = (file: string): string => {
  if (file.endsWith(".wasm")) return "application/wasm";
  if (file.endsWith(".json")) return "application/json";
  if (file.endsWith(".zip")) return "application/zip";
  return "text/javascript; charset=utf-8";
};

export const installPinnedPyodideAssets = async (
  context: PyodideAssetContext,
  directory = pyodidePayloadDirectory,
): Promise<void> => {
  const payload = await (directory === pyodidePayloadDirectory
    ? (preparedPayload ??= verifyPyodidePayload(directory))
    : verifyPyodidePayload(directory));
  await context.route(`${PYODIDE_CDN_ROOT}**`, async (route, request) => {
    const file = basename(new URL(request.url()).pathname);
    if (payload.files.includes(file)) {
      await route.fulfill({ path: join(payload.directory, file), contentType: contentType(file) });
    } else {
      await route.continue();
    }
  });
};
