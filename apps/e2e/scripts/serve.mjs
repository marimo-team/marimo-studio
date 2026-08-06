import { spawn } from "node:child_process";
import { cp, mkdir, rm } from "node:fs/promises";

import {
  fixtureDirectory,
  notebookPath,
  repositoryDirectory,
  workspaceDirectory,
} from "./paths.mjs";

await rm(workspaceDirectory, { force: true, recursive: true });
await mkdir(workspaceDirectory, { recursive: true });
await cp(fixtureDirectory, workspaceDirectory, { recursive: true });

const child = spawn(
  "uv",
  [
    "run",
    "--frozen",
    "--group",
    "e2e",
    "marimo",
    "edit",
    notebookPath,
    "--no-sandbox",
    "--headless",
    "--no-token",
    "--host",
    "127.0.0.1",
    "--port",
    "4321",
  ],
  {
    cwd: repositoryDirectory,
    detached: process.platform !== "win32",
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: "inherit",
  },
);

let stopping = false;
const serverUrl = "http://127.0.0.1:4321";

const killChildTree = (signal) => {
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
  const document = await fetch(`${serverUrl}/studio/dashboard/`).then((response) =>
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
  if (stopping || child.exitCode !== null) {
    return;
  }
  stopping = true;
  requestGracefulShutdown().catch(() => killChildTree(signal));
  setTimeout(() => {
    if (child.exitCode === null) {
      killChildTree("SIGKILL");
    }
  }, 5_000).unref();
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

child.on("error", (error) => {
  console.error(error);
  process.exitCode = 1;
});

child.on("exit", async (code, signal) => {
  await rm(workspaceDirectory, { force: true, recursive: true });
  process.exitCode = stopping && signal ? 0 : (code ?? 1);
});
