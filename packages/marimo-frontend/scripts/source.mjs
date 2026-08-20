import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { access, mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import { readMarimoSource } from "./metadata.mjs";

const exec = promisify(execFile);
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = resolve(packageRoot, "../..");
const corepackPackagePath = fileURLToPath(import.meta.resolve("corepack/package.json"));
const corepackPackage = JSON.parse(readFileSync(corepackPackagePath, "utf8"));
const corepackExecutable = resolve(dirname(corepackPackagePath), corepackPackage.bin.corepack);
const cacheRoot = join(packageRoot, ".cache");
const checkout = join(cacheRoot, "marimo");
const metadataPath = join(cacheRoot, "source.json");
const environmentRoot = resolve(
  workspaceRoot,
  process.env.UV_PROJECT_ENVIRONMENT?.trim() || ".venv",
);
const pythonExecutable =
  process.platform === "win32"
    ? join(environmentRoot, "Scripts", "python.exe")
    : join(environmentRoot, "bin", "python");

export const repository = "https://github.com/marimo-team/marimo.git";

const release = JSON.parse(
  readFileSync(
    resolve(packageRoot, "../marimo-studio/src/marimo_studio/_compat/release.json"),
    "utf8",
  ),
);
export const expectedVersion = release.version;
export const expectedCommit = release.commit;
export const expectedPatchSha256 = release.frontendPatchSha256;

if (patchManifest.baseCommit !== expectedCommit) {
  throw new Error("The Marimo frontend patch targets a different release commit");
}
if (patchManifest.sha256 !== expectedPatchSha256) {
  throw new Error("The Marimo frontend patch differs from the configured release identity");
}
if (createHash("sha256").update(patchContents).digest("hex") !== expectedPatchSha256) {
  throw new Error("The Marimo frontend patch digest is stale");
}

const capture = async (command, args, cwd, env) => {
  const result = await exec(command, args, { cwd, encoding: "utf8", env });
  return result.stdout.trim();
};

const captureRaw = async (command, args, cwd) => {
  const result = await exec(command, args, { cwd, encoding: "utf8" });
  return result.stdout;
};

const run = (command, args, cwd) =>
  new Promise((resolveRun, rejectRun) => {
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

export const pnpmInvocation = (
  args,
  { nodeExecutable = process.execPath, corepackExecutable: corepackCli = corepackExecutable } = {},
) => ({
  command: nodeExecutable,
  args: [corepackCli, "pnpm", ...args],
});

const runPnpm = async (args, cwd) => {
  const invocation = pnpmInvocation(args);
  await run(invocation.command, invocation.args, cwd);
};

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

const installedVersion = () =>
  capture(
    pythonExecutable,
    ["-B", "-c", "import marimo; print(marimo.__version__)"],
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

export const assertMarimoCommit = async (path) => {
  const actual = await capture("git", ["rev-parse", "HEAD"], path);
  if (actual !== expectedCommit) {
    throw new Error(
      `The Marimo checkout is ${actual}, but Studio requires release commit ${expectedCommit}`,
    );
  }
};

export const assertCleanCheckout = async (path) => {
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

export const assertMarimoPatch = async (path) => {
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
  const expected = comparablePatch(patchContents);
  if (observed !== expected) {
    const digest = createHash("sha256").update(observed).digest("hex");
    throw new Error(`The applied Marimo frontend patch has digest ${digest}`);
  }
  await exec("git", ["apply", "--reverse", "--check", patchPath], { cwd: path });
};

const applyMarimoPatch = async (path) => {
  await assertMarimoCommit(path);
  await assertCleanCheckout(path);
  await exec("git", ["apply", "--check", patchPath], { cwd: path });
  await exec("git", ["apply", patchPath], { cwd: path });
  await assertMarimoPatch(path);
};

const installWorkspace = async (path) => {
  await runPnpm(["install", "--frozen-lockfile"], path);
  await runPnpm(["--dir", "packages/llm-info", "codegen"], path);
};

const workspacePaths = (path) => [
  join(path, "node_modules", ".pnpm"),
  join(path, "frontend", "node_modules"),
  join(path, "packages", "llm-info", "data", "generated", "models.json"),
];

const isWorkspaceInstalled = async (path) =>
  (await Promise.all(workspacePaths(path).map(exists))).every(Boolean);

const remoteUrl = (path) => capture("git", ["remote", "get-url", "origin"], path);

const hasInstalledWorkspace = async (path) =>
  (await exists(join(path, "node_modules", ".pnpm"))) &&
  (await exists(join(path, "frontend", "node_modules"))) &&
  (await exists(join(path, "packages", "llm-info", "data", "generated", "models.json")));

export const prepareOwnedCheckout = async ({ path, repository, commit }) => {
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

export const isPreparedOwnedCheckout = async ({ path, repository, commit }) => {
  try {
    if (!(await exists(join(path, ".git")))) {
      return false;
    }
    const [origin, head, status] = await Promise.all([
      remoteUrl(path),
      capture("git", ["rev-parse", "HEAD"], path),
      capture("git", ["status", "--porcelain=v1", "--untracked-files=all"], path),
    ]);
    if (origin !== repository || head !== commit || status) {
      return false;
    }
    return isWorkspaceInstalled(path);
  } catch {
    return false;
  }
};

const reusableOwnedSource = async (version) => {
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
    return (await isPreparedPatchedCheckout(source)) ? source : null;
  } catch {
    return null;
  }
};

const refreshableOwnedCheckout = async (origin = repository) => {
  try {
    return (
      (await exists(join(checkout, ".git"))) &&
      (await remoteUrl(checkout)) === origin &&
      (await capture("git", ["rev-parse", "HEAD"], checkout)) === expectedCommit &&
      (await hasInstalledWorkspace(checkout))
    );
  } catch {
    return false;
  }
};

export const prepareMarimoSource = async () => {
  const version = await resolvedVersion();
  if (version !== expectedVersion) {
    throw new Error(
      `The Python environment resolves Marimo ${version}, but Studio requires ${expectedVersion}`,
    );
  }
  const configured = process.env.MARIMO_REPO?.trim();
  let path;

  if (configured) {
    path = resolve(configured);
    await assertVersion(path, version);
    await assertMarimoCommit(path);
    await assertCleanCheckout(path);
    if (!(await isWorkspaceInstalled(path))) {
      await installWorkspace(path);
    }
  } else {
    const reusable = await reusableOwnedSource(version);
    if (reusable) {
      return reusable;
    }
    path = checkout;
    if (await refreshableOwnedCheckout()) {
      await run("git", ["reset", "--hard", expectedCommit], checkout);
      await run("git", ["clean", "-ffd"], checkout);
      await assertMarimoCommit(checkout);
      await assertCleanCheckout(checkout);
    } else {
      await prepareOwnedCheckout({ path, repository, commit: expectedCommit });
      await installWorkspace(checkout);
    }
    await assertVersion(checkout, version);
    await applyMarimoPatch(path);
  }

  await assertMarimoCommit(path);
  await assertCleanCheckout(path);
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

export const assertPreparedMarimoSource = async () => {
  const version = await installedVersion();
  if (version !== expectedVersion) {
    throw new Error(
      `The Python environment resolves Marimo ${version}, but Studio requires ${expectedVersion}`,
    );
  }

  const source = await readMarimoSource();
  const configured = process.env.MARIMO_REPO?.trim();
  const expectedPath = configured ? resolve(configured) : checkout;
  if (
    source.commit !== expectedCommit ||
    source.path !== expectedPath ||
    source.repository !== repository ||
    source.version !== expectedVersion
  ) {
    throw new Error("The prepared Marimo source metadata does not match the configured release");
  }

  await assertMarimoCommit(source.path);
  await assertCleanCheckout(source.path);
  if (!configured && (await remoteUrl(source.path)) !== repository) {
    throw new Error("The prepared Marimo checkout has an unexpected origin");
  }
  if (!(await isWorkspaceInstalled(source.path))) {
    throw new Error(
      "The prepared Marimo checkout is missing frontend dependencies or generated data",
    );
  }
  return source;
};

export { readMarimoSource };
