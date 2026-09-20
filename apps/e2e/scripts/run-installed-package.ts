import { cp, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { INSTALLED_NETWORK_ENV } from "./installed-package-network.ts";

process.env.MARIMO_STUDIO_E2E_SUITE = "installed";
const { appDirectory, repositoryDirectory, blobReportDirectory, playwrightOutputDirectory } =
  await import("./paths.ts");
const { InstalledWorkspace } = await import("./installed-workspace.ts");
const { e2eNetwork } = await import("./network.ts");
import { PreparationCancelled, PreparationProcessOwner } from "./preparation-process.ts";

const wheelPattern = /^marimo_studio-.*\.whl$/;
const playwrightCli = fileURLToPath(import.meta.resolve("@playwright/test/cli"));
const installedBlobDirectory = blobReportDirectory;
const installedResultsDirectory = playwrightOutputDirectory;
const signalExitCodes = Object.freeze({
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143,
});

const builtWheel = async (wheelDirectory: string) => {
  const entries = await readdir(wheelDirectory, { withFileTypes: true });
  const wheels = entries
    .filter((entry) => entry.isFile() && wheelPattern.test(entry.name))
    .map((entry) => resolve(wheelDirectory, entry.name));
  const [wheel] = wheels;
  if (wheels.length !== 1 || wheel === undefined) {
    throw new Error(`Wheel build produced ${wheels.length} marimo-studio wheels`);
  }
  return wheel;
};

const preparation = new PreparationProcessOwner();
let exitCode = 0;
let stopping = false;
let temporaryRoot: string | undefined;
let workspace: InstanceType<typeof InstalledWorkspace> | undefined;

const removeStableArtifacts = () =>
  Promise.all(
    [installedBlobDirectory, installedResultsDirectory].map((path) =>
      rm(path, { force: true, recursive: true }),
    ),
  );

const preserveArtifact = async (source: string, destination: string) => {
  try {
    await mkdir(resolve(destination, ".."), { recursive: true });
    await cp(source, destination, { force: true, recursive: true });
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
  }
};

type StopSignal = keyof typeof signalExitCodes;
const stop = (signal: StopSignal) => {
  if (stopping) return;
  stopping = true;
  exitCode = signalExitCodes[signal];
  void Promise.all([preparation.stop(signal), workspace?.close()]).catch((error) => {
    console.error(error);
    exitCode = 1;
  });
};

const signals: StopSignal[] = ["SIGINT", "SIGTERM", "SIGHUP"];
const signalHandlers = new Map(signals.map((signal) => [signal, () => stop(signal)]));
for (const [signal, handler] of signalHandlers) {
  process.on(signal, handler);
}

try {
  await removeStableArtifacts();
  temporaryRoot = await mkdtemp(resolve(tmpdir(), "marimo-studio-installed-wheel-e2e-"));
  let wheel = process.env.MARIMO_STUDIO_E2E_WHEEL;
  if (!wheel) {
    const wheelDirectory = resolve(temporaryRoot, "wheel");
    await mkdir(wheelDirectory);
    await preparation.run(
      "build marimo-studio wheel",
      "uv",
      ["build", "--package", "marimo-studio", "--wheel", "--out-dir", wheelDirectory],
      { cwd: repositoryDirectory, stdio: "inherit" },
    );
    wheel = await builtWheel(wheelDirectory);
  }
  preparation.requireActive();
  await e2eNetwork.start();
  preparation.requireActive();
  workspace = new InstalledWorkspace(temporaryRoot);
  const network = await workspace.prepare(wheel);
  const serviceExit = workspace.waitForExit();
  await Promise.race([
    serviceExit,
    preparation.run(
      "run installed-wheel Playwright acceptance",
      process.execPath,
      [
        playwrightCli,
        "test",
        "--config",
        "playwright.installed.config.ts",
        ...process.argv.slice(2),
      ],
      {
        cwd: appDirectory,
        env: {
          ...process.env,
          [INSTALLED_NETWORK_ENV]: JSON.stringify(network),
          MARIMO_STUDIO_E2E_INSTALLED_OUTPUT_ROOT: temporaryRoot,
          MARIMO_STUDIO_E2E_WHEEL: wheel,
        },
        stdio: "inherit",
      },
    ),
  ]);
} catch (error) {
  if (!(stopping && error instanceof PreparationCancelled)) {
    console.error(error);
  }
  if (!stopping) exitCode = 1;
} finally {
  try {
    const results = await Promise.allSettled([preparation.stop("SIGTERM"), workspace?.close()]);
    const errors = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    if (errors.length > 0) {
      console.error(new AggregateError(errors, "Installed acceptance shutdown failed"));
      exitCode = 1;
    }
  } catch (error) {
    console.error(error);
    exitCode = 1;
  }
  try {
    await e2eNetwork.close();
  } catch (error) {
    console.error(error);
    exitCode = 1;
  }
  if (temporaryRoot) {
    try {
      await preserveArtifact(resolve(temporaryRoot, "blob"), installedBlobDirectory);
    } catch (error) {
      console.error(error);
      exitCode = 1;
    }
    if (exitCode !== 0) {
      try {
        await preserveArtifact(resolve(temporaryRoot, "playwright"), installedResultsDirectory);
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
