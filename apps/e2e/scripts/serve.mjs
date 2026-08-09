import { spawn } from "node:child_process";
import { cp, mkdir, rm } from "node:fs/promises";

import {
  configDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  repositoryDirectory,
  workspaceDirectory,
} from "./paths.mjs";

await rm(configDirectory, { force: true, recursive: true });
await mkdir(configDirectory, { recursive: true });
for (const [fixture, workspace] of [
  [fixtureDirectory, workspaceDirectory],
  [hostedFixtureDirectory, hostedWorkspaceDirectory],
]) {
  await rm(workspace, { force: true, recursive: true });
  await mkdir(workspace, { recursive: true });
  await cp(fixture, workspace, { recursive: true });
}

const startServer = (args) =>
  spawn("uv", ["run", "--frozen", "--group", "e2e", "marimo", "edit", ...args], {
    cwd: repositoryDirectory,
    detached: process.platform !== "win32",
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      XDG_CONFIG_HOME: configDirectory,
      _MARIMO_CONFIG_OVERLOAD_RUNTIME_AUTO_INSTANTIATE: "true",
    },
    stdio: "inherit",
  });

const primary = startServer([
  workspaceDirectory,
  "--no-sandbox",
  "--headless",
  "--no-token",
  "--host",
  "127.0.0.1",
  "--port",
  "4321",
]);
const hosted = startServer([
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
  "4322",
]);
const children = [primary, hosted];

let stopping = false;
let exitCode = 0;
const exited = new Set();
const serverUrl = "http://127.0.0.1:4321";

const killChildTree = (child, signal) => {
  if (process.platform === "win32" || child.pid === undefined) {
    child.kill(signal);
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") {
      throw error;
    }
  }
};

const requestGracefulShutdown = async () => {
  const document = await fetch(`${serverUrl}/?file=notebook.py`).then((response) =>
    response.text(),
  );
  const token = document.match(/"serverToken":"([^"]+)"/)?.[1];
  if (!token) {
    throw new Error("Studio bootstrap did not contain a server token");
  }
  const response = await fetch(`${serverUrl}/api/kernel/shutdown`, {
    method: "POST",
    headers: { "Marimo-Server-Token": token },
  });
  if (!response.ok) {
    throw new Error(`Marimo shutdown returned ${response.status}`);
  }
};

const stop = (signal) => {
  if (stopping) {
    return;
  }
  stopping = true;
  if (primary.exitCode === null) {
    requestGracefulShutdown().catch(() => killChildTree(primary, signal));
  }
  if (hosted.exitCode === null) {
    killChildTree(hosted, signal);
  }
  setTimeout(() => {
    for (const child of children) {
      if (child.exitCode === null) {
        killChildTree(child, "SIGKILL");
      }
    }
  }, 5_000).unref();
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

for (const child of children) {
  child.on("error", (error) => {
    console.error(error);
    exitCode = 1;
    stop("SIGTERM");
  });
  child.on("exit", async (code, signal) => {
    exited.add(child);
    if (!stopping) {
      exitCode = code === 0 && !signal ? 1 : (code ?? 1);
      stop("SIGTERM");
    }
    if (exited.size !== children.length) {
      return;
    }
    await Promise.all(
      [configDirectory, workspaceDirectory, hostedWorkspaceDirectory].map(async (workspace) =>
        rm(workspace, { force: true, recursive: true }),
      ),
    );
    process.exitCode = exitCode;
  });
}
