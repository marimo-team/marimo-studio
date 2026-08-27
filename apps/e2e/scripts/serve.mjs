import { spawn } from "node:child_process";
import { cp, mkdir, rm } from "node:fs/promises";

import { e2eNetwork } from "./network.mjs";
import {
  closeNotebookProcessRegistry,
  stopRegisteredNotebookProcesses,
} from "./notebook-process-registry.mjs";
import {
  configDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  lazyNotebookPath,
  repositoryDirectory,
  staticExportDirectory,
  workspaceDirectory,
} from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import { captureProcessOutput, stopNotebookProcess, waitForServer } from "./server-process.mjs";

const outputs = new WeakMap();
const startServer = (args) => {
  const child = spawn("uv", ["run", "--frozen", "--group", "e2e", "marimo", "edit", ...args], {
    cwd: repositoryDirectory,
    detached: process.platform !== "win32",
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      XDG_CONFIG_HOME: configDirectory,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  outputs.set(
    child,
    captureProcessOutput(child, { stdout: process.stdout, stderr: process.stderr }),
  );
  return child;
};

const preparation = new PreparationProcessOwner();
let primary;
let hosted;
let exported;
let stopping = false;
let exitCode = 0;
const closures = [];
const shutdowns = [];

const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  closeNotebookProcessRegistry();
  shutdowns.push(
    preparation.stop(signal).catch((error) => {
      console.error(error);
      exitCode = 1;
    }),
  );
  shutdowns.push(
    stopRegisteredNotebookProcesses({ signal }).catch((error) => {
      console.error(error);
      exitCode = 1;
    }),
  );
  for (const server of [
    primary && {
      child: primary,
      output: outputs.get(primary),
      port: e2eNetwork.main.studio.port,
      serverUrl: e2eNetwork.main.studio.origin,
      shutdown: "studio",
    },
    hosted && {
      authToken: "studio-e2e-token",
      child: hosted,
      output: outputs.get(hosted),
      port: e2eNetwork.main.hosted.port,
      serverUrl: `${e2eNetwork.main.hosted.origin}/hosted`,
      shutdown: "studio",
    },
    exported && {
      child: exported,
      port: e2eNetwork.main.exported.port,
      serverUrl: e2eNetwork.main.exported.origin,
      shutdown: "process",
    },
  ]) {
    if (!server) continue;
    shutdowns.push(
      stopNotebookProcess(server, { shutdown: server.shutdown, signal }).catch((error) => {
        console.error(error);
        exitCode = 1;
      }),
    );
  }
};

const track = (child) => {
  closures.push(
    new Promise((resolve) => {
      child.on("error", (error) => {
        console.error(error);
        exitCode = 1;
        stop("SIGTERM");
      });
      child.on("exit", (code, signal) => {
        if (!stopping) {
          exitCode = code === 0 && !signal ? 1 : (code ?? 1);
          stop("SIGTERM");
        }
      });
      child.on("close", resolve);
    }),
  );
  return child;
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

try {
  preparation.requireActive();
  closeNotebookProcessRegistry();
  await stopRegisteredNotebookProcesses({ signal: "SIGKILL" });
  preparation.requireActive();
  await rm(configDirectory, { force: true, recursive: true });
  preparation.requireActive();
  await mkdir(configDirectory, { recursive: true });
  for (const [fixture, workspace] of [
    [fixtureDirectory, workspaceDirectory],
    [hostedFixtureDirectory, hostedWorkspaceDirectory],
  ]) {
    preparation.requireActive();
    await rm(workspace, { force: true, recursive: true });
    preparation.requireActive();
    await mkdir(workspace, { recursive: true });
    preparation.requireActive();
    await cp(fixture, workspace, { recursive: true });
  }

  await preparation.run(
    "static fixture export",
    "uv",
    [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo-studio",
      "view",
      "export",
      "dashboard",
      "--target",
      lazyNotebookPath,
      "--output",
      staticExportDirectory,
    ],
    {
      cwd: repositoryDirectory,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    },
  );
  preparation.requireActive();

  hosted = track(
    startServer([
      hostedNotebookPath,
      "--no-sandbox",
      "--headless",
      "--token-password",
      "studio-e2e-token",
      "--base-url",
      "/hosted",
      "--host",
      "127.0.0.1",
      "--port",
      String(e2eNetwork.main.hosted.port),
    ]),
  );
  exported = track(
    spawn(
      "uv",
      [
        "run",
        "--group",
        "e2e",
        "python",
        "-m",
        "http.server",
        String(e2eNetwork.main.exported.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        staticExportDirectory,
      ],
      {
        cwd: repositoryDirectory,
        detached: process.platform !== "win32",
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        stdio: "ignore",
      },
    ),
  );
  await Promise.all([
    waitForServer(
      hosted,
      `${e2eNetwork.main.hosted.origin}/hosted/?access_token=studio-e2e-token`,
      {
        output: outputs.get(hosted),
      },
    ),
    waitForServer(exported, `${e2eNetwork.main.exported.origin}/src/index.html`),
  ]);
  preparation.requireActive();
  primary = track(
    startServer([
      workspaceDirectory,
      "--no-sandbox",
      "--headless",
      "--no-token",
      "--host",
      "127.0.0.1",
      "--port",
      String(e2eNetwork.main.studio.port),
    ]),
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
try {
  closeNotebookProcessRegistry();
  await stopRegisteredNotebookProcesses({ signal: "SIGKILL" });
} catch (error) {
  console.error(error);
  exitCode = 1;
}
await Promise.all(
  [configDirectory, workspaceDirectory, hostedWorkspaceDirectory].map(async (workspace) =>
    rm(workspace, { force: true, recursive: true }),
  ),
);
process.exitCode = exitCode;
