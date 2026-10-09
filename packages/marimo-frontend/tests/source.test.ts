import { execFile } from "node:child_process";
import { access, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { expect, onTestFinished, test } from "vite-plus/test";

import manifest from "../package.json" with { type: "json" };
import { decodeMarimoSource } from "../scripts/metadata.ts";
import {
  assertCleanCheckout,
  assertMarimoCommit,
  expectedCommit,
  pnpmInvocation,
  prepareOwnedCheckout,
} from "../scripts/source.ts";

const exec = promisify(execFile);

const temporaryDirectory = async (prefix: string) => {
  const path = await mkdtemp(join(tmpdir(), prefix));
  onTestFinished(() =>
    rm(path, {
      force: true,
      maxRetries: 10,
      recursive: true,
      retryDelay: 20,
    }),
  );
  return path;
};

const git = async (cwd: string, ...args: string[]) =>
  (
    await exec("git", args, {
      cwd,
      encoding: "utf8",
      env: { ...process.env, GIT_TRACE2_EVENT: "0" },
    })
  ).stdout.trim();

const createRepository = async (content: string) => {
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

const isMissing = async (path: string) => {
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
        patchSha256: "a".repeat(64),
        path: "/tmp/marimo",
        repository: "https://github.com/marimo-team/marimo.git",
        version: "1.2.3",
        ignored: true,
      }),
    ),
  ).toEqual({
    commit: "abc123",
    patchSha256: "a".repeat(64),
    path: "/tmp/marimo",
    repository: "https://github.com/marimo-team/marimo.git",
    version: "1.2.3",
  });
  expect(() => decodeMarimoSource('{"commit":42}')).toThrow();
  expect(() => decodeMarimoSource("invalid")).toThrow();
});

test("package preparation invokes the workspace Corepack through Node", () => {
  const invocation = pnpmInvocation(["install", "--frozen-lockfile"]);
  expect(invocation.command).toBe(process.execPath);
  expect(invocation.args[0]).toMatch(/[/\\]corepack[/\\]dist[/\\]corepack\.js$/);
  expect(invocation.args.slice(1)).toEqual(["pnpm", "install", "--frozen-lockfile"]);
});

test("the package exposes capability facades", () => {
  expect(new Set(Object.keys(manifest.exports))).toEqual(
    new Set([
      "./arrow-table",
      "./build-metadata",
      "./cell-presentation",
      "./control-endpoint",
      "./embedded-runtime",
      "./editor-workspace",
      "./notebook-entry",
      "./prepared-presentation",
      "./projected-output",
      "./projected-output-function-gate",
      "./session-bootstrap",
      "./theme-frame",
      "./vite",
    ]),
  );
});

test("checkout preparation repairs ownership and local changes", async () => {
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
}, 15_000);

test("an owned clone leaves its local source checkout unchanged", async () => {
  const source = await createRepository("source\n");
  const checkout = await temporaryDirectory("marimo-studio-local-clone-");

  await writeFile(join(source.path, "tracked.txt"), "next release\n");
  await git(source.path, "commit", "-am", "next release");
  await writeFile(join(source.path, "tracked.txt"), "local edit\n");
  await writeFile(join(source.path, "untracked.txt"), "local file\n");
  const sourceHead = await git(source.path, "rev-parse", "HEAD");
  const sourceStatus = await git(source.path, "status", "--porcelain=v1", "--untracked-files=all");

  await prepareOwnedCheckout({
    path: checkout,
    repository: source.path,
    commit: source.commit,
  });
  await writeFile(join(checkout, "tracked.txt"), "owned change\n");
  await prepareOwnedCheckout({
    path: checkout,
    repository: source.path,
    commit: source.commit,
  });

  expect(await git(source.path, "rev-parse", "HEAD")).toBe(sourceHead);
  expect(await git(source.path, "status", "--porcelain=v1", "--untracked-files=all")).toBe(
    sourceStatus,
  );
  expect(await readFile(join(source.path, "tracked.txt"), "utf8")).toBe("local edit\n");
  expect(await readFile(join(source.path, "untracked.txt"), "utf8")).toBe("local file\n");
  expect(await readFile(join(checkout, "tracked.txt"), "utf8")).toBe("source\n");
});

test("an owned checkout must match the pinned release commit", async () => {
  const source = await createRepository("release\n");
  await expect(assertMarimoCommit(source.path)).rejects.toThrow(expectedCommit);
});

test("patch preparation requires a clean owned checkout", async () => {
  const source = await createRepository("release\n");

  await assertCleanCheckout(source.path);
  await writeFile(join(source.path, "tracked.txt"), "changed\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");

  await git(source.path, "checkout", "--", "tracked.txt");
  await writeFile(join(source.path, "untracked.ts"), "export {};\n");
  await expect(assertCleanCheckout(source.path)).rejects.toThrow("local source changes");
});

test("source acquisition rejects using the source as its owned checkout", async () => {
  const source = await createRepository("source\n");
  await expect(
    prepareOwnedCheckout({
      path: source.path,
      repository: source.path,
      commit: source.commit,
    }),
  ).rejects.toThrow("must be outside");
  expect(await readFile(join(source.path, "tracked.txt"), "utf8")).toBe("source\n");
});
