import { cp, mkdtemp, mkdir, rename, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, delimiter, isAbsolute, resolve } from "node:path";

import {
  createInstalledPackageNetwork,
  INSTALLED_NETWORK_FILE_ENV,
} from "./installed-package-network.mjs";
import { e2eNetwork } from "./network.mjs";
import { appDirectory, repositoryDirectory } from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import { startRoutedNotebookProcess } from "./routed-notebook-process.mjs";
import { stopNotebookProcess, waitForServer } from "./server-process.mjs";

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

const track = (server) => {
  const { child } = server;
  servers.push(server);
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
      child.once("exit", resolveClose);
    }),
  );
  return server;
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
  for (const serverProcess of servers) {
    const { shutdown, timeout } = serverProcess;
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
  await e2eNetwork.start();
  const installedPackageNetwork = createInstalledPackageNetwork(e2eNetwork.installed);
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
      "--exclude-newer-package",
      "marimo-lens=false",
      `${wheel}[lens]`,
      "anywidget>=0.11.0",
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
    "verify published dependencies",
    python,
    [
      "-c",
      [
        "from importlib.metadata import distribution, version",
        "from pathlib import Path",
        "from packaging.version import Version",
        "import marimo_lens, sys",
        "assert Version(version('marimo-lens')) >= Version('0.1.2')",
        "assert distribution('marimo-lens').read_text('direct_url.json') is None",
        "assert Path(marimo_lens.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())",
        "assert version('marimo-export') == '0.0.8'",
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

  const registryDirectory = resolve(temporaryRoot, "notebook-processes");
  const launch = async (endpoint, args, shutdown) => {
    preparation.requireActive();
    const service = track(
      Object.assign(
        startRoutedNotebookProcess({
          endpoint,
          command: python,
          args,
          cwd: workspaceDirectory,
          directory: registryDirectory,
          env: environment,
          forward: { stdout: process.stdout, stderr: process.stderr },
        }),
        { shutdown, timeout: 10_000 },
      ),
    );
    await service.ready;
    return service;
  };
  const marimoArgs = (command, target) => [
    resolve(repositoryDirectory, "apps/e2e/scripts/_compat/server.py"),
    "marimo",
    command,
    ...target,
    "--no-sandbox",
    "--headless",
    "--no-token",
  ];
  server = await launch(e2eNetwork.installed.edit, marimoArgs("edit", [notebookPath]), "studio");
  const freshServer = await launch(e2eNetwork.installed.fresh, marimoArgs("new", []), "studio");
  runServer = await launch(e2eNetwork.installed.run, marimoArgs("run", [notebookPath]), "run");
  exported = await launch(
    e2eNetwork.installed.static,
    [
      resolve(repositoryDirectory, "apps/e2e/scripts/static-server.py"),
      "0",
      "--bind",
      "127.0.0.1",
      "--directory",
      staticDirectory,
    ],
    "process",
  );
  await Promise.all([
    waitForServer(freshServer.child, freshServer.serverUrl, {
      output: freshServer.output,
      timeout: 120_000,
    }),
    waitForServer(server.child, `${server.serverUrl}/_marimo-studio/status`, {
      output: server.output,
      timeout: 120_000,
    }),
    waitForServer(runServer.child, `${runServer.serverUrl}/_marimo-studio/status`, {
      output: runServer.output,
      timeout: 120_000,
    }),
    waitForServer(exported.child, exported.serverUrl, {
      output: exported.output,
      timeout: 120_000,
    }),
  ]);
  const networkFile = process.env[INSTALLED_NETWORK_FILE_ENV];
  if (!networkFile || !isAbsolute(networkFile))
    throw new Error("Installed network manifest path is required");
  await writeFile(`${networkFile}.tmp`, JSON.stringify(installedPackageNetwork), {
    mode: 0o600,
    flag: "wx",
  });
  await rename(`${networkFile}.tmp`, networkFile);
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
await e2eNetwork.close();
if (temporaryRoot) {
  await rm(temporaryRoot, { force: true, maxRetries: 20, recursive: true, retryDelay: 50 });
}
process.exitCode = exitCode;
