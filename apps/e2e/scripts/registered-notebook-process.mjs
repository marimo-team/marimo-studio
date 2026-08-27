import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  createNotebookProcessOwnerNonce,
  NOTEBOOK_PROCESS_OWNER_ENV,
  NOTEBOOK_PROCESS_PORT_ENV,
  NOTEBOOK_PROCESS_REGISTRY_ENV,
} from "./notebook-process-registry.mjs";

const READY_TIMEOUT = 10_000;
const supervisorPath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "notebook-process-supervisor.mjs",
);

const supervisorReadiness = (child, timeout) => {
  let rejectPending;
  let resolveRegistered;
  let resolveStarted;
  const registered = new Promise((resolveReady, rejectReady) => {
    resolveRegistered = resolveReady;
    rejectPending = rejectReady;
  });
  const started = new Promise((resolveReady, rejectReady) => {
    resolveStarted = resolveReady;
    const rejectStarted = rejectReady;
    const rejectBoth = rejectPending;
    rejectPending = (error) => {
      rejectBoth(error);
      rejectStarted(error);
    };
  });
  void registered.catch(() => undefined);
  void started.catch(() => undefined);
  let settled = false;
  let startRequested = false;
  const fail = (error) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    rejectPending(error);
  };
  const timer = setTimeout(
    () => fail(new Error("Notebook process registration timed out")),
    timeout,
  );
  child.once("error", fail);
  child.once("exit", (code, signal) => {
    const status = signal ? `signal ${signal}` : `status ${code ?? 1}`;
    fail(new Error(`Notebook process supervisor exited with ${status}`));
  });
  child.on("message", (message) => {
    if (message?.type === "registered") resolveRegistered();
    if (message?.type === "started") {
      settled = true;
      clearTimeout(timer);
      resolveStarted();
    }
  });
  const start = async () => {
    await registered;
    if (!child.connected) {
      const error = new Error("Notebook process supervisor disconnected before start");
      fail(error);
      throw error;
    }
    if (!startRequested) {
      startRequested = true;
      await new Promise((resolveSent, rejectSent) => {
        child.send({ type: "start" }, (error) =>
          error ? rejectSent(error) : resolveSent(undefined),
        );
      });
    }
    await started;
  };
  return Object.freeze({ registered, start });
};

export const spawnRegisteredNotebookSupervisor = ({
  args,
  command,
  cwd,
  directory,
  env,
  port,
  readyTimeout = READY_TIMEOUT,
  stdio = ["ignore", "pipe", "pipe"],
}) => {
  const ownerNonce = createNotebookProcessOwnerNonce();
  const child = spawn(process.execPath, [supervisorPath, command, ...args], {
    cwd,
    detached: process.platform !== "win32",
    env: {
      ...env,
      [NOTEBOOK_PROCESS_OWNER_ENV]: ownerNonce,
      [NOTEBOOK_PROCESS_PORT_ENV]: String(port),
      [NOTEBOOK_PROCESS_REGISTRY_ENV]: directory,
    },
    stdio: [...stdio, "ipc"],
  });
  const processGroupId = child.pid;
  if (processGroupId === undefined) {
    child.once("error", () => undefined);
    child.kill("SIGKILL");
    throw new Error("Notebook process supervisor did not expose a process group ID");
  }
  const readiness = supervisorReadiness(child, readyTimeout);
  return Object.freeze({
    child,
    ownerNonce,
    processGroupId,
    registered: readiness.registered,
    start: readiness.start,
  });
};

export const startRegisteredNotebookProcess = (options) => {
  const supervisor = spawnRegisteredNotebookSupervisor(options);
  const ready = supervisor.start().catch((error) => {
    if (supervisor.child.connected) supervisor.child.disconnect();
    throw error;
  });
  return Object.freeze({ ...supervisor, ready });
};
