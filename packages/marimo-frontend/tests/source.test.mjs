import { execFile } from "node:child_process";
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, expect, test } from "vite-plus/test";

import { decodeMarimoSource } from "../scripts/metadata.mjs";
import {
  assertCleanCheckout,
  assertMarimoCommit,
  expectedCommit,
  isPreparedOwnedCheckout,
  prepareOwnedCheckout,
} from "../scripts/source.mjs";

const exec = promisify(execFile);
const temporaryPaths = [];

const temporaryDirectory = async (prefix) => {
  const path = await mkdtemp(join(tmpdir(), prefix));
  temporaryPaths.push(path);
  return path;
};

afterEach(async () => {
  await Promise.all(
    temporaryPaths.splice(0).map((path) => rm(path, { force: true, recursive: true })),
  );
});

const git = async (cwd, ...args) =>
  (await exec("git", args, { cwd, encoding: "utf8" })).stdout.trim();

const createRepository = async (content) => {
  const path = await temporaryDirectory("marimo-studio-source-");
  await git(path, "init");
  await git(path, "config", "user.email", "studio@example.com");
  await git(path, "config", "user.name", "Marimo Studio");
  await writeFile(join(path, ".gitignore"), "node_modules/\npackages/llm-info/data/generated/\n");
  await writeFile(join(path, "tracked.txt"), content);
  await git(path, "add", ".gitignore", "tracked.txt");
  await git(path, "commit", "-m", "fixture");
  return { commit: await git(path, "rev-parse", "HEAD"), path };
};

const isMissing = async (path) => {
  try {
    await access(path);
    return false;
  } catch {
    return true;
  }
};

test("source metadata validates the prepared checkout contract", () => {
  expect(
    decodeMarimoSource(
      JSON.stringify({
        commit: "abc123",
        path: "/tmp/marimo",
        repository: "https://github.com/marimo-team/marimo.git",
        version: "1.2.3",
        ignored: true,
      }),
    ),
  ).toEqual({
    commit: "abc123",
    path: "/tmp/marimo",
    repository: "https://github.com/marimo-team/marimo.git",
    version: "1.2.3",
  });
  expect(() => decodeMarimoSource('{"commit":42}')).toThrow();
  expect(() => decodeMarimoSource("invalid")).toThrow();
});

test("the package exposes capability facades", async () => {
  const manifest = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));

  expect(new Set(Object.keys(manifest.exports))).toEqual(
    new Set([
      "./build-metadata",
      "./cell-presentation",
      "./control-endpoint",
      "./embedded-runtime",
      "./projected-output",
      "./session-bootstrap",
      "./theme-frame",
      "./vite",
    ]),
  );
});

test("checkout preparation repairs ownership, dirt, and readiness", async () => {
  const expected = await createRepository("expected\n");
  const other = await createRepository("other\n");
  const checkout = await temporaryDirectory("marimo-studio-checkout-");
  const preparation = {
    path: checkout,
    repository: expected.path,
    commit: expected.commit,
  };

  await prepareOwnedCheckout({
    path: checkout,
    repository: other.path,
    commit: other.commit,
  });
  await prepareOwnedCheckout(preparation);

  expect(await git(checkout, "remote", "get-url", "origin")).toBe(expected.path);
  expect(await git(checkout, "rev-parse", "HEAD")).toBe(expected.commit);
  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("expected\n");

  await writeFile(join(checkout, "tracked.txt"), "changed\n");
  await writeFile(join(checkout, "untracked.txt"), "changed\n");
  await prepareOwnedCheckout(preparation);

  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("expected\n");
  expect(await isMissing(join(checkout, "untracked.txt"))).toBe(true);
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);

  await Promise.all([
    mkdir(join(checkout, "node_modules", ".pnpm"), { recursive: true }),
    mkdir(join(checkout, "frontend", "node_modules"), { recursive: true }),
    mkdir(join(checkout, "packages", "llm-info", "data", "generated"), {
      recursive: true,
    }),
  ]);
  await writeFile(
    join(checkout, "packages", "llm-info", "data", "generated", "models.json"),
    "{}\n",
  );

  expect(await isPreparedOwnedCheckout(preparation)).toBe(true);

  await writeFile(join(checkout, "untracked.ts"), "export {};\n");
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);
  await rm(join(checkout, "untracked.ts"));

  await writeFile(join(checkout, "tracked.txt"), "changed\n");
  expect(await isPreparedOwnedCheckout(preparation)).toBe(false);
});

test("a local source must match the tagged release commit", async () => {
  const source = await createRepository("release\n");
  await expect(assertMarimoCommit(source.path)).rejects.toThrow(expectedCommit);
});

test("a local source must have a clean worktree", async () => {
  const source = await createRepository("release\n");

  await assertCleanCheckout(source.path);
  await writeFile(join(source.path, "tracked.txt"), "changed\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");

  await git(source.path, "checkout", "--", "tracked.txt");
  await writeFile(join(source.path, "untracked.ts"), "export {};\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");
});
