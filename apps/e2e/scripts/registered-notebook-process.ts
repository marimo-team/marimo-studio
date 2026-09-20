import { spawn, type ChildProcess, type IOType, type Serializable } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import {
  createNotebookProcessOwnerNonce,
  NOTEBOOK_PROCESS_OWNER_ENV,
  NOTEBOOK_PROCESS_PORT_ENV,
  NOTEBOOK_PROCESS_REGISTRY_ENV,
} from "./notebook-process-registry.ts";

const supervisorMessageSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("registered") }),
  z.object({ type: z.literal("started") }),
  z.object({ type: z.literal("bound"), port: z.number().int().positive().max(65_535) }),
  z.object({ type: z.literal("failed"), message: z.string() }),
]);
export type SupervisorMessage = z.infer<typeof supervisorMessageSchema>;

const READY_TIMEOUT = 10_000;
const supervisorPath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "notebook-process-supervisor.ts",
);

export interface SupervisorOptions {
  args: string[];
  command: string;
  cwd: string;
  directory: string;
  env: NodeJS.ProcessEnv;
  port?: number | null;
  boundTimeout?: number;
  readyTimeout?: number;
  stdio?: IOType[];
}

const supervisorReadiness = (
  child: ChildProcess,
  timeout: number,
  boundTimeout: number,
  port: number | null,
  missingProcessGroup: boolean,
) => {
  const registered = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const bound = Promise.withResolvers<number>();
  for (const pending of [registered, started, bound]) {
    void pending.promise.catch(() => undefined);
  }
  let failure: Error | undefined;
  let registeredReceived = false;
  let startedReceived = false;
  let startRequested = false;
  let timer: NodeJS.Timeout | undefined;
  const dispose = () => {
    clearTimeout(timer);
    child.off("error", onError);
    child.off("exit", onExit);
    child.off("message", onMessage);
  };
  const fail = (error: Error) => {
    if (failure) return;
    failure = error;
    dispose();
    registered.reject(error);
    started.reject(error);
    bound.reject(error);
    if (child.connected) child.disconnect();
  };
  const armTimeout = (message: string, duration: number) => {
    clearTimeout(timer);
    timer = setTimeout(() => fail(new Error(message)), duration);
  };
  const onError = (error: Error) =>
    fail(
      missingProcessGroup
        ? new Error("Notebook process supervisor did not expose a process group ID", {
            cause: error,
          })
        : error,
    );
  const onExit = (code: number | null, signal: NodeJS.Signals | null) => {
    const status = signal ? `signal ${signal}` : `status ${code ?? 1}`;
    fail(new Error(`Notebook process supervisor exited with ${status}`));
  };
  const onMessage = (source: Serializable) => {
    const parsed = supervisorMessageSchema.safeParse(source);
    if (!parsed.success) {
      fail(new Error("Invalid notebook supervisor message", { cause: parsed.error }));
      return;
    }
    const message = parsed.data;
    if (message.type === "failed") {
      fail(new Error(message.message));
    } else if (message.type === "registered" && !registeredReceived) {
      registeredReceived = true;
      clearTimeout(timer);
      registered.resolve();
    } else if (message.type === "started" && startRequested && !startedReceived) {
      startedReceived = true;
      clearTimeout(timer);
      started.resolve();
      if (port !== null) {
        bound.resolve(port);
        dispose();
      } else {
        armTimeout("Notebook backend binding timed out", boundTimeout);
      }
    } else if (message.type === "bound" && startedReceived && port === null) {
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
        await new Promise<void>((resolveSent, rejectSent) => {
          child.send({ type: "start" }, (error) =>
            error ? rejectSent(error) : resolveSent(undefined),
          );
        });
      } catch (error) {
        fail(
          error instanceof Error
            ? error
            : new Error("Notebook supervisor start failed", { cause: error }),
        );
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
  port = null,
  boundTimeout = 60_000,
  readyTimeout = READY_TIMEOUT,
  stdio = ["ignore", "pipe", "pipe"],
}: SupervisorOptions) => {
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

export const startRegisteredNotebookProcess = (options: SupervisorOptions) => {
  const supervisor = spawnRegisteredNotebookSupervisor(options);
  const ready = supervisor.start().catch((error) => {
    if (supervisor.child.connected) supervisor.child.disconnect();
    throw error;
  });
  return Object.freeze({ ...supervisor, ready });
};
