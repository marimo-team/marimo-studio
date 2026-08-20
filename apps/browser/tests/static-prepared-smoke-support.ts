import { readFile } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";

const STATIC_SMOKE_ORIGIN = new URL("https://marimo-studio.invalid/");

const within = (root: string, path: string): boolean =>
  path === root || path.startsWith(`${root}${sep}`);

const requestUrl = (input: RequestInfo | URL): URL => {
  if (input instanceof Request) return new URL(input.url);
  if (input instanceof URL) return input;
  return new URL(input);
};

export const staticSmokeUrl = (siteRoot: string, source: string): URL => {
  const root = resolve(siteRoot);
  const path = resolve(source);
  if (!within(root, path)) {
    throw new Error("The static smoke source is outside the staged site.");
  }
  const relativePath = relative(root, path).split(sep).map(encodeURIComponent).join("/");
  return new URL(relativePath, STATIC_SMOKE_ORIGIN);
};

export const staticSmokeFetch = (siteRoot: string): typeof fetch => {
  const root = resolve(siteRoot);
  return async (input) => {
    const url = requestUrl(input);
    if (url.origin !== STATIC_SMOKE_ORIGIN.origin) {
      throw new Error(`The static smoke received an external URL: ${url.href}`);
    }
    const relativePath = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    const path = resolve(root, relativePath);
    if (!within(root, path)) {
      throw new Error(`The static smoke URL escapes the staged site: ${url.href}`);
    }
    try {
      return new Response(await readFile(path), { status: 200 });
    } catch (error) {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") {
        return new Response(null, { status: 404 });
      }
      throw error;
    }
  };
};
