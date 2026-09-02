import { spawn } from "node:child_process";
import { connect } from "node:net";

import {
  NOTEBOOK_PROCESS_OWNER_ENV,
  NOTEBOOK_PROCESS_PORT_ENV,
  NOTEBOOK_PROCESS_REGISTRY_ENV,
  registerNotebookProcess,
  unregisterNotebookProcess,
} from "./notebook-process-registry.mjs";
import { stopProcessGroup } from "./process-group.mjs";

const FORCE_STOP_DELAY = 250;
const PORT_CLOSE_TIMEOUT = 5_000;
const PORT_POLL_INTERVAL = 50;
const command = process.argv[2];
const args = process.argv.slice(3);
const directory = process.env[NOTEBOOK_PROCESS_REGISTRY_ENV];
const ownerNonce = process.env[NOTEBOOK_PROCESS_OWNER_ENV];
const port = Number(process.env[NOTEBOOK_PROCESS_PORT_ENV]);
const processGroupId = process.pid;

if (!command || !directory || !ownerNonce || !Number.isSafeInteger(port)) {
  throw new Error("Notebook process supervisor received an invalid registration");
}

registerNotebookProcess({ ownerNonce, port, processGroupId }, { directory });

const childEnvironment = { ...process.env };
delete childEnvironment[NOTEBOOK_PROCESS_PORT_ENV];
delete childEnvironment[NOTEBOOK_PROCESS_REGISTRY_ENV];

let child;
let childExitCode = 1;
let finished = false;
let forceStopTimer;
let shuttingDown = false;

const send = (message) => {
  if (!process.connected || !process.send) return;
  try {
    process.send(message, () => undefined);
  } catch {
    beginShutdown(true);
  }
};

const portIsOpen = () =>
  new Promise((resolveOpen) => {
    const socket = connect({ host: "127.0.0.1", port });
    const finish = (open) => {
      socket.destroy();
      resolveOpen(open);
    };
    socket.setTimeout(100, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });

const finish = () => {
  if (finished) return;
  finished = true;
  clearTimeout(forceStopTimer);
  unregisterNotebookProcess({ ownerNonce, processGroupId }, { directory });
  process.exitCode = childExitCode;
  if (process.connected) process.disconnect();
};

const finishWhenPortCloses = async (deadline = Date.now() + PORT_CLOSE_TIMEOUT) => {
  if (finished) return;
  if (await portIsOpen()) {
    if (Date.now() >= deadline) {
      finish();
      forceStop();
      return;
    }
    setTimeout(() => void finishWhenPortCloses(deadline), PORT_POLL_INTERVAL);
    return;
  }
  finish();
};

const forceStop = () => {
  if (process.platform === "win32") {
    stopProcessGroup(child?.pid, "SIGKILL");
    return;
  }
  process.kill(-processGroupId, "SIGKILL");
};

const beginShutdown = (signalGroup, force = true) => {
  if (shuttingDown || finished) return;
  shuttingDown = true;
  childExitCode = 1;
  if (force) forceStopTimer = setTimeout(forceStop, FORCE_STOP_DELAY);
  if (signalGroup) {
    if (process.platform === "win32") stopProcessGroup(child?.pid, "SIGTERM");
    else process.kill(-processGroupId, "SIGTERM");
  }
  if (!child) finish();
};

const start = () => {
  if (child || shuttingDown || !process.connected) return;
  child = spawn(command, args, {
    cwd: process.cwd(),
    env: childEnvironment,
    stdio: ["ignore", "inherit", "inherit"],
  });
  child.once("error", (error) => {
    console.error(error);
    beginShutdown(false);
    finish();
  });
  child.once("spawn", () => {
    send({ type: "started" });
  });
  child.once("exit", (code, signal) => {
    childExitCode = signal ? 1 : (code ?? 1);
    void finishWhenPortCloses();
  });
};

process.on("disconnect", () => beginShutdown(true));
process.on("SIGINT", () => beginShutdown(true, false));
process.on("SIGHUP", () => beginShutdown(true, false));
process.on("SIGTERM", () => beginShutdown(true, false));
process.on("message", (message) => {
  if (message?.type === "start") start();
});

if (!process.connected || !process.send) {
  finish();
} else {
  send({ type: "registered" });
}
