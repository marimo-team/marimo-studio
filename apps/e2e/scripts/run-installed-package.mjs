import { cp, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { appDirectory, repositoryDirectory } from "./paths.mjs";
import { PreparationCancelled, PreparationProcessOwner } from "./preparation-process.mjs";

const wheelPattern = /^marimo_studio-.*\.whl$/;
const playwrightCli = fileURLToPath(import.meta.resolve("@playwright/test/cli"));
const installedReportDirectory = resolve(appDirectory, "playwright-report-installed");
const installedResultsDirectory = resolve(appDirectory, "test-results", "installed-playwright");
const signalExitCodes = Object.freeze({
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143,
});

const builtWheel = async (wheelDirectory) => {
  const entries = await readdir(wheelDirectory, { withFileTypes: true });
  const wheels = entries
    .filter((entry) => entry.isFile() && wheelPattern.test(entry.name))
    .map((entry) => resolve(wheelDirectory, entry.name));
  if (wheels.length !== 1) {
    throw new Error(`Wheel build produced ${wheels.length} marimo-studio wheels`);
  }
  return wheels[0];
};

const preparation = new PreparationProcessOwner();
let exitCode = 0;
let stopping = false;
let temporaryRoot;

const removeStableArtifacts = () =>
  Promise.all(
    [installedReportDirectory, installedResultsDirectory].map((path) =>
      rm(path, { force: true, recursive: true }),
    ),
  );

const preserveFailureArtifact = async (source, destination) => {
  try {
    await mkdir(resolve(destination, ".."), { recursive: true });
    await cp(source, destination, { force: true, recursive: true });
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
};

const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  exitCode = signalExitCodes[signal] ?? 1;
  void preparation.stop(signal).catch((error) => {
    console.error(error);
    exitCode = 1;
  });
};

const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
const signalHandlers = new Map(signals.map((signal) => [signal, () => stop(signal)]));
for (const [signal, handler] of signalHandlers) {
  process.on(signal, handler);
}

try {
  await removeStableArtifacts();
  temporaryRoot = await mkdtemp(resolve(tmpdir(), "marimo-studio-installed-wheel-e2e-"));
  const wheelDirectory = resolve(temporaryRoot, "wheel");
  await mkdir(wheelDirectory);
  await preparation.run(
    "build marimo-studio wheel",
    "uv",
    ["build", "--package", "marimo-studio", "--wheel", "--out-dir", wheelDirectory],
    { cwd: repositoryDirectory, stdio: "inherit" },
  );
  preparation.requireActive();
  const wheel = await builtWheel(wheelDirectory);
  await preparation.run(
    "run installed-wheel Playwright acceptance",
    process.execPath,
    [playwrightCli, "test", "--config", "playwright.installed.config.ts"],
    {
      cwd: appDirectory,
      env: {
        ...process.env,
        MARIMO_STUDIO_E2E_INSTALLED_OUTPUT_ROOT: temporaryRoot,
        MARIMO_STUDIO_E2E_WHEEL: wheel,
      },
      stdio: "inherit",
    },
  );
} catch (error) {
  if (!(stopping && error instanceof PreparationCancelled)) {
    console.error(error);
  }
  if (!stopping) exitCode = 1;
} finally {
  try {
    await preparation.stop("SIGTERM");
  } catch (error) {
    console.error(error);
    exitCode = 1;
  }
  if (temporaryRoot) {
    if (exitCode !== 0) {
      try {
        await Promise.all([
          preserveFailureArtifact(resolve(temporaryRoot, "report"), installedReportDirectory),
          preserveFailureArtifact(resolve(temporaryRoot, "playwright"), installedResultsDirectory),
        ]);
      } catch (error) {
        console.error(error);
        exitCode = 1;
      }
    }
    try {
      await rm(temporaryRoot, {
        force: true,
        maxRetries: 20,
        recursive: true,
        retryDelay: 50,
      });
    } catch (error) {
      console.error(error);
      exitCode = 1;
    }
  }
  for (const [signal, handler] of signalHandlers) {
    process.off(signal, handler);
  }
}

process.exitCode = exitCode;
