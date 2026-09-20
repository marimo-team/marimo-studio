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

const supervisorReadiness = (child, timeout, boundTimeout, port, missingProcessGroup) => {
  /** @type {PromiseWithResolvers<void>} */
  const registered = Promise.withResolvers();
  /** @type {PromiseWithResolvers<void>} */
  const started = Promise.withResolvers();
  /** @type {PromiseWithResolvers<number>} */
  const bound = Promise.withResolvers();
  for (const pending of [registered, started, bound]) {
    void pending.promise.catch(() => undefined);
  }
  let failure;
  let registeredReceived = false;
  let startedReceived = false;
  let startRequested = false;
  let timer;
  const dispose = () => {
    clearTimeout(timer);
    child.off("error", onError);
    child.off("exit", onExit);
    child.off("message", onMessage);
  };
  const fail = (error) => {
    if (failure) return;
    failure = error;
    dispose();
    registered.reject(error);
    started.reject(error);
    bound.reject(error);
    if (child.connected) child.disconnect();
  };
  const armTimeout = (message, duration) => {
    clearTimeout(timer);
    timer = setTimeout(() => fail(new Error(message)), duration);
  };
  const onError = (error) =>
    fail(
      missingProcessGroup
        ? new Error("Notebook process supervisor did not expose a process group ID", {
            cause: error,
          })
        : error,
    );
  const onExit = (code, signal) => {
    const status = signal ? `signal ${signal}` : `status ${code ?? 1}`;
    fail(new Error(`Notebook process supervisor exited with ${status}`));
  };
  const onMessage = (message) => {
    if (message?.type === "failed") {
      fail(new Error(String(message.message)));
    } else if (message?.type === "registered" && !registeredReceived) {
      registeredReceived = true;
      clearTimeout(timer);
      registered.resolve();
    } else if (message?.type === "started" && startRequested && !startedReceived) {
      startedReceived = true;
      clearTimeout(timer);
      started.resolve();
      if (port !== null) {
        bound.resolve(port);
        dispose();
      } else {
        armTimeout("Notebook backend binding timed out", boundTimeout);
      }
    } else if (message?.type === "bound" && startedReceived && port === null) {
      if (!Number.isSafeInteger(message.port) || message.port < 1 || message.port > 65535) {
        fail(new Error("Notebook process supervisor returned an invalid backend port"));
        return;
      }
      bound.resolve(message.port);
      dispose();
    }
  };
  child.once("error", onError);
  child.once("exit", onExit);
  child.on("message", onMessage);
  armTimeout("Notebook process registration timed out", timeout);
  const start = async () => {
    await registered.promise;
    if (failure) throw failure;
    if (!child.connected) {
      const error = new Error("Notebook process supervisor disconnected before start");
      fail(error);
      throw error;
    }
    if (!startRequested) {
      startRequested = true;
      armTimeout("Notebook process start timed out", timeout);
      try {
        await new Promise((resolveSent, rejectSent) => {
          child.send({ type: "start" }, (error) =>
            error ? rejectSent(error) : resolveSent(undefined),
          );
        });
      } catch (error) {
        fail(error);
        throw error;
      }
    }
    await started.promise;
  };
  return Object.freeze({ registered: registered.promise, bound: bound.promise, start });
};

export const spawnRegisteredNotebookSupervisor = ({
  args,
  command,
  cwd,
  directory,
  env,
  port = /** @type {number | null} */ (null),
  boundTimeout = 60_000,
  readyTimeout = READY_TIMEOUT,
  stdio = ["ignore", "pipe", "pipe"],
}) => {
  const ownerNonce = createNotebookProcessOwnerNonce();
  /** @type {import("node:child_process").ChildProcess} */
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
  const readiness = supervisorReadiness(
    child,
    readyTimeout,
    boundTimeout,
    port,
    processGroupId === undefined,
  );
  return Object.freeze({
    child,
    ownerNonce,
    processGroupId,
    registered: readiness.registered,
    bound: readiness.bound,
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
