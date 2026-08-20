import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { afterEach, expect, it } from "vite-plus/test";

import { staticSmokeFetch, staticSmokeUrl } from "./static-prepared-smoke-support.ts";

const temporaryPaths: string[] = [];

const temporaryDirectory = async (): Promise<string> => {
  const path = await mkdtemp(resolve(tmpdir(), "marimo-studio-static-smoke-"));
  temporaryPaths.push(path);
  return path;
};

afterEach(async () => {
  await Promise.all(temporaryPaths.splice(0).map((path) => rm(path, { recursive: true })));
});

it("maps the staged site through the smoke HTTPS origin", async () => {
  const root = await temporaryDirectory();
  const source = resolve(root, "prepared", "index.json");
  await mkdir(dirname(source), { recursive: true });
  await writeFile(source, '{"schema":1}\n', "utf8");

  const url = staticSmokeUrl(root, source);
  const response = await staticSmokeFetch(root)(url);

  expect(url.href).toBe("https://marimo-studio.invalid/prepared/index.json");
  expect(await response.text()).toBe('{"schema":1}\n');
});

it("rejects local paths and URLs outside the staged site", async () => {
  const root = await temporaryDirectory();

  expect(() => staticSmokeUrl(root, resolve(root, "../outside.json"))).toThrow(
    /outside the staged site/,
  );
  await expect(staticSmokeFetch(root)(new URL("file:///tmp/outside.json"))).rejects.toThrow(
    /external URL/,
  );
  await expect(
    staticSmokeFetch(root)(new URL("https://marimo-studio.invalid/%2e%2e%2foutside.json")),
  ).rejects.toThrow(/escapes the staged site/);
});
