import { spawn } from "node:child_process";
import { cp, mkdtemp, mkdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, delimiter, isAbsolute, resolve } from "node:path";

import { installedPackageNetwork } from "./installed-package-network.mjs";
import { appDirectory, repositoryDirectory } from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import { captureProcessOutput, stopNotebookProcess, waitForServer } from "./server-process.mjs";

const fixtureDirectory = resolve(appDirectory, "fixtures-installed");

const installedWheel = async () => {
  const wheel = process.env.MARIMO_STUDIO_E2E_WHEEL;
  if (!wheel || !isAbsolute(wheel) || !/^marimo_studio-.*\.whl$/.test(basename(wheel))) {
    throw new Error("MARIMO_STUDIO_E2E_WHEEL must name an absolute marimo-studio wheel path");
  }
  const metadata = await stat(wheel).catch((error) => {
    throw new Error(`Installed-package wheel is unavailable at ${wheel}`, { cause: error });
  });
  if (!metadata.isFile()) {
    throw new Error(`Installed-package wheel is not a file: ${wheel}`);
  }
  return wheel;
};

const environmentExecutable = (environmentDirectory, name) =>
  resolve(
    environmentDirectory,
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? `${name}.exe` : name,
  );

const outputs = new WeakMap();
const preparation = new PreparationProcessOwner();
const closures = [];
const servers = [];
const shutdowns = [];
let exitCode = 0;
let exported;
let runServer;
let server;
let stopping = false;
let temporaryRoot;

const track = ({ child, ...server }) => {
  servers.push({
    child,
    ...server,
    output: () => outputs.get(child)?.() ?? "",
  });
  closures.push(
    new Promise((resolveClose) => {
      child.once("error", (error) => {
        console.error(error);
        exitCode = 1;
        stop("SIGTERM");
      });
      child.once("exit", (code, signal) => {
        if (!stopping) {
          exitCode = code === 0 && signal === null ? 1 : (code ?? 1);
          stop("SIGTERM");
        }
      });
      child.once("close", resolveClose);
    }),
  );
  return child;
};

const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  shutdowns.push(
    preparation.stop(signal).catch((error) => {
      console.error(error);
      exitCode = 1;
    }),
  );
  for (const { shutdown, timeout, ...serverProcess } of servers) {
    shutdowns.push(
      stopNotebookProcess(serverProcess, { shutdown, signal, timeout }).catch((error) => {
        console.error(error);
        exitCode = 1;
      }),
    );
  }
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

try {
  const wheel = await installedWheel();
  preparation.requireActive();
  temporaryRoot = await mkdtemp(resolve(tmpdir(), "marimo-studio-installed-e2e-"));
  const environmentDirectory = resolve(temporaryRoot, "environment");
  const workspaceDirectory = resolve(temporaryRoot, "workspace");
  const configDirectory = resolve(temporaryRoot, "xdg-config");
  const notebookPath = resolve(workspaceDirectory, "notebook.py");
  const staticDirectory = resolve(temporaryRoot, "static");
  const preparedDirectory = resolve(staticDirectory, "prepared");
  const viewDirectory = resolve(
    workspaceDirectory,
    "__marimo__",
    "studio",
    "notebook",
    "dashboard",
  );
  const python = environmentExecutable(environmentDirectory, "python");
  const marimo = environmentExecutable(environmentDirectory, "marimo");
  const studio = environmentExecutable(environmentDirectory, "marimo-studio");

  await mkdir(configDirectory, { recursive: true });
  await cp(fixtureDirectory, workspaceDirectory, { recursive: true });
  await preparation.run(
    "create installed-package environment",
    "uv",
    [
      "venv",
      environmentDirectory,
      ...(process.env.MARIMO_STUDIO_E2E_PYTHON
        ? ["--python", process.env.MARIMO_STUDIO_E2E_PYTHON]
        : []),
    ],
    { cwd: repositoryDirectory, stdio: "inherit" },
  );
  preparation.requireActive();
  await preparation.run(
    "install marimo-studio wheel",
    "uv",
    [
      "pip",
      "install",
      "--python",
      python,
      "--no-cache",
      "--exclude-newer-package",
      "marimo-export=false",
      wheel,
      "anywidget==0.9.21",
    ],
    { cwd: temporaryRoot, stdio: "inherit" },
  );
  preparation.requireActive();

  const environment = {
    ...process.env,
    PATH: `${resolve(environmentDirectory, process.platform === "win32" ? "Scripts" : "bin")}${delimiter}${process.env.PATH ?? ""}`,
    PYTHONNOUSERSITE: "1",
    PYTHONSAFEPATH: "1",
    PYTHONUNBUFFERED: "1",
    XDG_CONFIG_HOME: configDirectory,
    MARIMO_EXPORT_REPOSITORY: resolve(temporaryRoot, "export-repository"),
  };
  delete environment.PYTHONHOME;
  delete environment.PYTHONPATH;
  delete environment.UV_PROJECT_ENVIRONMENT;
  delete environment.VIRTUAL_ENV;
  await preparation.run(
    "verify published marimo-export installation",
    python,
    [
      "-c",
      [
        "from importlib.metadata import distribution, version",
        "assert version('marimo-export') == '0.0.3'",
        "assert distribution('marimo-export').read_text('direct_url.json') is None",
      ].join("; "),
    ],
    { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
  );
  preparation.requireActive();
  await preparation.run(
    "create installed Vanilla view",
    studio,
    [
      "view",
      "create",
      "dashboard",
      "--target",
      notebookPath,
      "--starter",
      "marimo-studio/vanilla:default",
      "--json",
    ],
    { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
  );
  preparation.requireActive();
  await cp(resolve(workspaceDirectory, "dashboard.html"), resolve(viewDirectory, "index.html"), {
    force: true,
  });
  await cp(resolve(workspaceDirectory, "states.yaml"), resolve(viewDirectory, "states.yaml"));
  await preparation.run(
    "build installed Vanilla view",
    studio,
    ["view", "build", "dashboard", "--target", notebookPath, "--json"],
    { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
  );
  preparation.requireActive();
  await preparation.run(
    "export installed Vanilla view",
    studio,
    [
      "view",
      "export",
      "dashboard",
      "--target",
      notebookPath,
      "--output",
      staticDirectory,
      "--runtime",
      "wasm",
      "--json",
    ],
    { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
  );
  preparation.requireActive();

  await preparation.run(
    "export installed prepared view",
    studio,
    [
      "view",
      "export",
      "dashboard",
      "--target",
      notebookPath,
      "--output",
      preparedDirectory,
      "--runtime",
      "zero-python",
      "--prepare-timeout",
      "120",
      "--json",
    ],
    { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
  );
  preparation.requireActive();

  server = track({
    child: spawn(
      marimo,
      [
        "edit",
        notebookPath,
        "--no-sandbox",
        "--headless",
        "--no-token",
        "--host",
        "127.0.0.1",
        "--port",
        String(installedPackageNetwork.port),
      ],
      {
        cwd: workspaceDirectory,
        detached: process.platform !== "win32",
        env: environment,
        stdio: ["ignore", "pipe", "pipe"],
      },
    ),
    port: installedPackageNetwork.port,
    serverUrl: installedPackageNetwork.origin,
    shutdown: "studio",
    timeout: 10_000,
  });
  outputs.set(
    server,
    captureProcessOutput(server, { stdout: process.stdout, stderr: process.stderr }),
  );
  runServer = track({
    child: spawn(
      marimo,
      [
        "run",
        notebookPath,
        "--no-sandbox",
        "--headless",
        "--no-token",
        "--host",
        "127.0.0.1",
        "--port",
        String(installedPackageNetwork.run.port),
      ],
      {
        cwd: workspaceDirectory,
        detached: process.platform !== "win32",
        env: environment,
        stdio: ["ignore", "pipe", "pipe"],
      },
    ),
    port: installedPackageNetwork.run.port,
    serverUrl: installedPackageNetwork.run.origin,
    shutdown: "run",
    timeout: 10_000,
  });
  outputs.set(
    runServer,
    captureProcessOutput(runServer, { stdout: process.stdout, stderr: process.stderr }),
  );
  exported = track({
    child: spawn(
      python,
      [
        "-m",
        "http.server",
        String(installedPackageNetwork.static.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        staticDirectory,
      ],
      {
        cwd: workspaceDirectory,
        detached: process.platform !== "win32",
        env: environment,
        stdio: ["ignore", "pipe", "pipe"],
      },
    ),
    port: installedPackageNetwork.static.port,
    serverUrl: installedPackageNetwork.static.origin,
    shutdown: "process",
    timeout: 10_000,
  });
  outputs.set(
    exported,
    captureProcessOutput(exported, { stdout: process.stdout, stderr: process.stderr }),
  );
  await Promise.all([
    waitForServer(server, `${installedPackageNetwork.origin}/_marimo-studio/status`, {
      output: outputs.get(server),
      timeout: 120_000,
    }),
    waitForServer(runServer, `${installedPackageNetwork.run.origin}/_marimo-studio/status`, {
      output: outputs.get(runServer),
      timeout: 120_000,
    }),
    waitForServer(exported, installedPackageNetwork.static.origin, {
      output: outputs.get(exported),
      timeout: 120_000,
    }),
  ]);
  await writeFile(
    resolve(staticDirectory, installedPackageNetwork.readiness.path.slice(1)),
    "ready\n",
  );
  await Promise.all(closures);
} catch (error) {
  if (!stopping) {
    console.error(error);
    exitCode = 1;
    stop("SIGTERM");
  }
  await Promise.allSettled(closures);
}

await Promise.allSettled(shutdowns);
if (temporaryRoot) {
  await rm(temporaryRoot, { force: true, maxRetries: 20, recursive: true, retryDelay: 50 });
}
process.exitCode = exitCode;
