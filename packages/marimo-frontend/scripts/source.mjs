import { execFile, spawn } from "node:child_process";
import { access, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import { readMarimoSource } from "./metadata.mjs";

const exec = promisify(execFile);
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = resolve(packageRoot, "../..");
const cacheRoot = join(packageRoot, ".cache");
const checkout = join(cacheRoot, "marimo");
const metadataPath = join(cacheRoot, "source.json");

export const repository = "https://github.com/marimo-team/marimo.git";

// Keep this revision aligned with the Marimo release resolved by uv.lock.
export const expectedCommit = "d9d6ca0d262845abafd52966790e1ffd4668da76";

const capture = async (command, args, cwd) => {
  const result = await exec(command, args, { cwd, encoding: "utf8" });
  return result.stdout.trim();
};

const run = (command, args, cwd) =>
  new Promise((resolveRun, rejectRun) => {
    const child = spawn(command, args, { cwd, stdio: "inherit" });
    child.on("error", rejectRun);
    child.on("exit", (code, signal) => {
      if (code === 0) {
        resolveRun();
        return;
      }
      rejectRun(
        new Error(
          signal
            ? `${command} exited after signal ${signal}`
            : `${command} exited with status ${code}`,
        ),
      );
    });
  });

const exists = async (path) => {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
};

const resolvedVersion = () =>
  capture(
    "uv",
    [
      "--color",
      "never",
      "run",
      "--frozen",
      "python",
      "-c",
      "import marimo; print(marimo.__version__)",
    ],
    workspaceRoot,
  );

const projectVersion = (path) =>
  capture("uv", ["--color", "never", "--project", path, "version", "--short"], workspaceRoot);

const assertVersion = async (path, expected) => {
  const actual = await projectVersion(path);
  if (actual !== expected) {
    throw new Error(
      `The Marimo checkout is ${actual}, but the Python environment resolves ${expected}`,
    );
  }
};

const installWorkspace = async (path) => {
  await run("corepack", ["pnpm", "install", "--frozen-lockfile"], path);
  await run("corepack", ["pnpm", "--dir", "packages/llm-info", "codegen"], path);
};

const remoteUrl = (path) => capture("git", ["remote", "get-url", "origin"], path);

export const prepareOwnedCheckout = async ({ path, repository, commit }) => {
  if ((await exists(join(path, ".git"))) && (await remoteUrl(path)) !== repository) {
    await rm(path, { force: true, recursive: true });
  }

  if (!(await exists(join(path, ".git")))) {
    await mkdir(dirname(path), { recursive: true });
    await run(
      "git",
      ["clone", "--filter=blob:none", "--no-checkout", repository, path],
      workspaceRoot,
    );
  }

  await run("git", ["fetch", "--depth=1", "--force", "origin", commit], path);
  await run("git", ["reset", "--hard"], path);
  await run("git", ["clean", "-ffdx"], path);
  await run("git", ["checkout", "--detach", commit], path);
  await run("git", ["reset", "--hard", commit], path);

  const actual = await capture("git", ["rev-parse", "HEAD"], path);
  if (actual !== commit) {
    throw new Error(`The Marimo checkout resolved ${actual}, expected ${commit}`);
  }
};

export const isPreparedOwnedCheckout = async ({ path, repository, commit }) => {
  try {
    if (!(await exists(join(path, ".git")))) {
      return false;
    }
    const [origin, head, status] = await Promise.all([
      remoteUrl(path),
      capture("git", ["rev-parse", "HEAD"], path),
      capture("git", ["status", "--porcelain=v1", "--untracked-files=no"], path),
    ]);
    if (origin !== repository || head !== commit || status) {
      return false;
    }
    return (
      (await exists(join(path, "node_modules", ".pnpm"))) &&
      (await exists(join(path, "frontend", "node_modules"))) &&
      (await exists(join(path, "packages", "llm-info", "data", "generated", "models.json")))
    );
  } catch {
    return false;
  }
};

const reusableOwnedSource = async (version) => {
  try {
    const source = await readMarimoSource();
    const matches =
      source.commit === expectedCommit &&
      source.path === checkout &&
      source.repository === repository &&
      source.version === version;
    if (!matches) {
      return null;
    }
    return (await isPreparedOwnedCheckout(source)) ? source : null;
  } catch {
    return null;
  }
};

export const prepareMarimoSource = async () => {
  const version = await resolvedVersion();
  const configured = process.env.MARIMO_REPO?.trim();
  let path;

  if (configured) {
    path = resolve(configured);
    await assertVersion(path, version);
  } else {
    const reusable = await reusableOwnedSource(version);
    if (reusable) {
      return reusable;
    }
    path = checkout;
    await prepareOwnedCheckout({ path, repository, commit: expectedCommit });
    await installWorkspace(checkout);
    await assertVersion(checkout, version);
  }

  const commit = await capture("git", ["rev-parse", "HEAD"], path);
  const source = { commit, path, repository, version };
  await mkdir(cacheRoot, { recursive: true });
  await writeFile(metadataPath, `${JSON.stringify(source, null, 2)}\n`);
  return source;
};

export { readMarimoSource };
