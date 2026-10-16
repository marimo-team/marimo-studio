import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vite-plus/test";

import { sourceDigest, workspaceSources } from "../build-metadata.ts";

let root: string;

const write = async (path: string) => {
  await mkdir(dirname(join(root, path)), { recursive: true });
  await writeFile(join(root, path), "");
};

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "build-sources-"));
  for (const path of [
    "pnpm-lock.yaml",
    "apps/browser/package.json",
    "apps/browser/vite.config.ts",
    "apps/browser/src/studio.ts",
    "packages/studio/package.json",
    "packages/studio/src/style.css",
    "packages/studio/src/app/studio.css",
    "packages/studio/src/workers/only-in-worker.ts",
    "packages/studio/src/.generated/ignored.ts",
    "packages/studio/tests/style.test.ts",
    "packages/unused/package.json",
    "packages/unused/src/index.ts",
    "apps/docs/package.json",
    "apps/docs/examples.ts",
    "packages/marimo-frontend/package.json",
    "packages/marimo-frontend/.cache/marimo/frontend/src/app.tsx",
    "node_modules/zod/package.json",
    "node_modules/zod/index.js",
  ]) {
    await write(path);
  }
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("workspaceSources", () => {
  it("records the source tree of each workspace package the build imports", async () => {
    const sources = await workspaceSources(
      root,
      [
        join(root, "apps", "browser", "src", "studio.ts"),
        `${join(root, "packages", "studio", "src", "style.css")}?inline`,
        join(root, "apps", "docs", "examples.ts"),
      ],
      [join(root, "apps", "browser", "vite.config.ts")],
    );

    expect(sources).toEqual([
      "apps/browser/package.json",
      "apps/browser/src/studio.ts",
      "apps/browser/vite.config.ts",
      "apps/docs/examples.ts",
      "apps/docs/package.json",
      "packages/studio/package.json",
      "packages/studio/src/app/studio.css",
      "packages/studio/src/style.css",
      "packages/studio/src/workers/only-in-worker.ts",
      "pnpm-lock.yaml",
    ]);
  });

  it("leaves dependencies, prepared checkouts, and virtual modules to their own identities", async () => {
    const sources = await workspaceSources(
      root,
      [
        join(root, "node_modules", "zod", "index.js"),
        join(root, "packages", "marimo-frontend", ".cache", "marimo", "frontend", "src", "app.tsx"),
        join(tmpdir(), "elsewhere", "module.ts"),
        "\0virtual:marimo",
        "virtual:relative",
      ],
      [],
    );

    expect(sources).toEqual(["pnpm-lock.yaml"]);
  });
});

describe("sourceDigest", () => {
  it("hashes content with LF line endings", () => {
    const lf = "911169ddaaf146aff539f58c26c489af3b892dff0fe283c1c264c65ae5aa59a2";

    expect(sourceDigest(Buffer.from("a\nb\n"))).toBe(lf);
    expect(sourceDigest(Buffer.from("a\r\nb\r\n"))).toBe(lf);
  });
});
