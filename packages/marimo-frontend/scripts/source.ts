import corepackManifest from "corepack/package.json" with { type: "json" };
import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { access, mkdir, realpath, rm, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import type { MarimoSource } from "./metadata.ts";

import release from "../../marimo-studio/src/marimo_studio/_compat/release.json" with { type: "json" };
import patchManifest from "../patches/marimo-frontend.json" with { type: "json" };
import { readMarimoSource } from "./metadata.ts";

interface OwnedCheckout {
  readonly path: string;
  readonly repository: string;
  readonly commit: string;
}

const exec = promisify(execFile);
const packageRoot = resolve(import.meta.dirname, "..");
const workspaceRoot = resolve(packageRoot, "../..");
const corepackExecutable = resolve(
  dirname(fileURLToPath(import.meta.resolve("corepack/package.json"))),
  corepackManifest.bin.corepack,
);
const cacheRoot = join(packageRoot, ".cache");
const checkout = join(cacheRoot, "marimo");
const metadataPath = join(cacheRoot, "source.json");
const patchPath = resolve(packageRoot, "patches", patchManifest.file);
const patchContents = readFileSync(patchPath);
const comparablePatch = (value: string): string =>
  value.replace(/^index [\da-f]+\.\.[\da-f]+(?: \d+)?\n/gmu, "");
const environmentRoot = resolve(
  workspaceRoot,
  process.env.UV_PROJECT_ENVIRONMENT?.trim() || ".venv",
);
const pythonExecutable =
  process.platform === "win32"
    ? join(environmentRoot, "Scripts", "python.exe")
    : join(environmentRoot, "bin", "python");

const repository = "https://github.com/marimo-team/marimo.git";
const expectedVersion = release.version;
export const expectedCommit = release.commit;
const expectedPatchSha256 = release.frontendPatchSha256;

if (patchManifest.baseCommit !== expectedCommit) {
  throw new Error("The Marimo frontend patch targets a different release commit");
}
if (patchManifest.sha256 !== expectedPatchSha256) {
  throw new Error("The Marimo frontend patch differs from the configured release identity");
}
if (createHash("sha256").update(patchContents).digest("hex") !== expectedPatchSha256) {
  throw new Error("The Marimo frontend patch digest is stale");
}

const capture = async (
  command: string,
  args: readonly string[],
  cwd: string,
  env?: NodeJS.ProcessEnv,
): Promise<string> => {
  const result = await exec(command, args, { cwd, encoding: "utf8", env });
  return result.stdout.trim();
};

const captureRaw = async (command: string, args: readonly string[], cwd: string) => {
  const result = await exec(command, args, { cwd, encoding: "utf8" });
  return result.stdout;
};

const run = (command: string, args: readonly string[], cwd: string) =>
  new Promise<void>((resolveRun, rejectRun) => {
    const child = spawn(command, args, { cwd, stdio: "inherit" });
    child.once("error", rejectRun);
    child.once("close", (code, signal) => {
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

export const pnpmInvocation = (args: readonly string[]) => ({
  command: process.execPath,
  args: [corepackExecutable, "pnpm", ...args],
});

const runPnpm = async (args: readonly string[], cwd: string) => {
  const invocation = pnpmInvocation(args);
  await run(invocation.command, invocation.args, cwd);
};

const exists = async (path: string): Promise<boolean> => {
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

const installedVersion = () =>
  capture(
    pythonExecutable,
    ["-B", "-c", "import marimo; print(marimo.__version__)"],
    workspaceRoot,
  );

const projectVersion = (path: string) =>
  capture("uv", ["--color", "never", "--project", path, "version", "--short"], workspaceRoot);

const assertVersion = async (path: string, expected: string) => {
  const actual = await projectVersion(path);
  if (actual !== expected) {
    throw new Error(
      `The Marimo checkout is ${actual}, but the Python environment resolves ${expected}`,
    );
  }
};

export const assertMarimoCommit = async (path: string) => {
  const actual = await capture("git", ["rev-parse", "HEAD"], path);
  if (actual !== expectedCommit) {
    throw new Error(
      `The Marimo checkout is ${actual}, but Studio requires release commit ${expectedCommit}`,
    );
  }
};

export const assertCleanCheckout = async (path: string) => {
  const status = await capture("git", ["status", "--porcelain=v1", "--untracked-files=all"], path, {
    ...process.env,
    GIT_OPTIONAL_LOCKS: "0",
  });
  if (status) {
    throw new Error(
      "The Marimo checkout has local source changes. Studio requires the configured release commit.",
    );
  }
};

const patchedFiles = [
  "frontend/src/components/ui/native-select.tsx",
  "frontend/src/components/ui/slider.tsx",
  "frontend/src/core/kernel/__tests__/session.test.ts",
  "frontend/src/core/kernel/session.ts",
  "frontend/src/core/websocket/__tests__/useWebSocket.test.ts",
  "frontend/src/core/websocket/useWebSocket.tsx",
  "frontend/src/plugins/core/__test__/registerReactComponent.test.ts",
  "frontend/src/plugins/core/registerReactComponent.tsx",
  "frontend/src/plugins/impl/__tests__/DropdownPlugin.test.tsx",
  "frontend/src/plugins/impl/__tests__/SliderPlugin.test.tsx",
  "frontend/src/plugins/impl/SliderPlugin.tsx",
  "frontend/src/plugins/impl/anywidget/__tests__/model.test.ts",
  "frontend/src/plugins/impl/anywidget/__tests__/registry.test.ts",
  "frontend/src/plugins/impl/anywidget/model.ts",
  "frontend/src/plugins/impl/anywidget/registry.ts",
  "frontend/src/plugins/impl/anywidget/runtime.ts",
  "frontend/src/plugins/impl/common/labeled.tsx",
];

const assertMarimoPatch = async (path: string) => {
  await assertMarimoCommit(path);
  const status = await captureRaw(
    "git",
    ["status", "--porcelain=v1", "--untracked-files=all"],
    path,
  );
  const changed = status
    .trimEnd()
    .split("\n")
    .filter(Boolean)
    .map((entry) => entry.slice(3))
    .sort();
  if (JSON.stringify(changed) !== JSON.stringify(patchedFiles.toSorted())) {
    throw new Error("The Marimo checkout contains changes outside the frontend patch");
  }
  const diff = await captureRaw(
    "git",
    ["diff", "--no-ext-diff", "--binary", "--", ...patchedFiles],
    path,
  );
  const observed = comparablePatch(diff);
  const expected = comparablePatch(patchContents.toString("utf8"));
  if (observed !== expected) {
    const digest = createHash("sha256").update(observed).digest("hex");
    throw new Error(`The applied Marimo frontend patch has digest ${digest}`);
  }
  await exec("git", ["apply", "--reverse", "--check", patchPath], { cwd: path });
};

const applyMarimoPatch = async (path: string) => {
  await assertMarimoCommit(path);
  await assertCleanCheckout(path);
  await exec("git", ["apply", "--check", patchPath], { cwd: path });
  await exec("git", ["apply", patchPath], { cwd: path });
  await assertMarimoPatch(path);
};

const installWorkspace = async (path: string) => {
  await runPnpm(["install", "--frozen-lockfile"], path);
  await runPnpm(["--dir", "packages/llm-info", "codegen"], path);
};

const workspacePaths = (path: string) => [
  join(path, "node_modules", ".pnpm"),
  join(path, "frontend", "node_modules"),
  join(path, "packages", "llm-info", "data", "generated", "models.json"),
];

const isWorkspaceInstalled = async (path: string): Promise<boolean> =>
  (await Promise.all(workspacePaths(path).map(exists))).every(Boolean);

const remoteUrl = (path: string) => capture("git", ["remote", "get-url", "origin"], path);

export const prepareOwnedCheckout = async ({ path, repository, commit }: OwnedCheckout) => {
  if (await exists(repository)) {
    const source = await realpath(repository);
    const owned = (await exists(path)) ? await realpath(path) : resolve(path);
    const sourceFromOwned = relative(owned, source);
    if (
      sourceFromOwned === "" ||
      (!isAbsolute(sourceFromOwned) &&
        sourceFromOwned !== ".." &&
        !sourceFromOwned.startsWith(`..${sep}`))
    ) {
      throw new Error("The Marimo source repository must be outside Studio's owned checkout");
    }
  }
  if ((await exists(join(path, ".git"))) && (await remoteUrl(path)) !== repository) {
    await rm(path, {
      force: true,
      maxRetries: 10,
      recursive: true,
      retryDelay: 20,
    });
  }

  if (!(await exists(join(path, ".git")))) {
    await mkdir(dirname(path), { recursive: true });
    const cloneOptions = (await exists(repository)) ? [] : ["--filter=blob:none"];
    await run("git", ["clone", ...cloneOptions, "--no-checkout", repository, path], workspaceRoot);
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

const isPreparedPatchedCheckout = async ({ path, repository, commit }: OwnedCheckout) => {
  try {
    if (!(await exists(join(path, ".git"))) || (await remoteUrl(path)) !== repository) {
      return false;
    }
    if ((await capture("git", ["rev-parse", "HEAD"], path)) !== commit) {
      return false;
    }
    await assertMarimoPatch(path);
    return isWorkspaceInstalled(path);
  } catch {
    return false;
  }
};

const reusableOwnedSource = async (version: string, origin: string) => {
  try {
    const source = await readMarimoSource();
    const matches =
      source.commit === expectedCommit &&
      source.patchSha256 === expectedPatchSha256 &&
      source.path === checkout &&
      source.repository === repository &&
      source.version === version;
    if (!matches) {
      return null;
    }
    return (await isPreparedPatchedCheckout({ ...source, repository: origin })) ? source : null;
  } catch {
    return null;
  }
};

const refreshableOwnedCheckout = async (origin: string) => {
  try {
    return (
      (await exists(join(checkout, ".git"))) &&
      (await remoteUrl(checkout)) === origin &&
      (await capture("git", ["rev-parse", "HEAD"], checkout)) === expectedCommit &&
      (await isWorkspaceInstalled(checkout))
    );
  } catch {
    return false;
  }
};

const sourceRepository = () => {
  const configured = process.env.MARIMO_REPO?.trim();
  return configured ? resolve(configured) : repository;
};

export const prepareMarimoSource = async (): Promise<MarimoSource> => {
  const version = await resolvedVersion();
  if (version !== expectedVersion) {
    throw new Error(
      `The Python environment resolves Marimo ${version}, but Studio requires ${expectedVersion}`,
    );
  }
  const origin = sourceRepository();
  const reusable = await reusableOwnedSource(version, origin);
  if (reusable) {
    return reusable;
  }
  const path = checkout;
  if (await refreshableOwnedCheckout(origin)) {
    await run("git", ["reset", "--hard", expectedCommit], path);
    await run("git", ["clean", "-ffd"], path);
    await assertMarimoCommit(path);
    await assertCleanCheckout(path);
  } else {
    await prepareOwnedCheckout({ path, repository: origin, commit: expectedCommit });
    await installWorkspace(path);
  }
  await assertVersion(path, version);
  await applyMarimoPatch(path);

  await assertMarimoCommit(path);
  await assertMarimoPatch(path);
  const commit = await capture("git", ["rev-parse", "HEAD"], path);
  const source = {
    commit,
    patchSha256: expectedPatchSha256,
    path,
    repository,
    version,
  };
  await mkdir(cacheRoot, { recursive: true });
  await writeFile(metadataPath, `${JSON.stringify(source, null, 2)}\n`);
  return source;
};

export const assertPreparedMarimoSource = async (): Promise<MarimoSource> => {
  const version = await installedVersion();
  if (version !== expectedVersion) {
    throw new Error(
      `The Python environment resolves Marimo ${version}, but Studio requires ${expectedVersion}`,
    );
  }

  const source = await readMarimoSource();
  const origin = sourceRepository();
  if (
    source.commit !== expectedCommit ||
    source.patchSha256 !== expectedPatchSha256 ||
    source.path !== checkout ||
    source.repository !== repository ||
    source.version !== expectedVersion
  ) {
    throw new Error("The prepared Marimo source metadata does not match the configured release");
  }

  await assertMarimoCommit(source.path);
  await assertMarimoPatch(source.path);
  if ((await remoteUrl(source.path)) !== origin) {
    throw new Error("The prepared Marimo checkout has an unexpected origin");
  }
  if (!(await isWorkspaceInstalled(source.path))) {
    throw new Error(
      "The prepared Marimo checkout is missing frontend dependencies or generated data",
    );
  }
  return source;
};
