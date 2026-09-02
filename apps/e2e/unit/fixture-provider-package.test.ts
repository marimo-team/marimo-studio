import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { copyFixtureProviderPackage } from "../scripts/fixture-provider-package.mjs";
import { externalProviderPackage } from "../scripts/paths.mjs";

test("copies the fixture provider into an arbitrary workspace", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-fixture-provider-"));
  const workspace = resolve(root, "workspace");
  const destination = resolve(workspace, "../fixtures-provider/provider");
  try {
    await mkdir(destination, { recursive: true });
    await writeFile(resolve(destination, "stale.py"), "stale");
    await copyFixtureProviderPackage(workspace);

    const sourceManifest = await readFile(resolve(externalProviderPackage, "pyproject.toml"));
    const copiedManifest = await readFile(resolve(destination, "pyproject.toml"));
    expect(copiedManifest).toEqual(sourceManifest);
    await expect(readFile(resolve(destination, "stale.py"), "utf8")).rejects.toThrow();
  } finally {
    await rm(root, { force: true, recursive: true });
  }
});
