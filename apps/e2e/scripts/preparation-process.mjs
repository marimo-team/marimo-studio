import { spawn as spawnChild } from "node:child_process";

import { processGroupIsRunning, stopProcessGroup } from "./process-group.mjs";

const DEFAULT_STOP_TIMEOUT = 5_000;
const STOP_POLL_INTERVAL = 50;
/** @type {(command: string, args: string[], options: import("node:child_process").SpawnOptions) => import("node:child_process").ChildProcess} */
const defaultSpawn = spawnChild;

export class PreparationCancelled extends Error {
  constructor(options) {
    super("E2E preparation was cancelled", options);
    this.name = "PreparationCancelled";
  }
}

const recordIsRunning = (record) => {
  if (record.processGroupId === undefined) return !record.settled;
  const group = processGroupIsRunning(record.processGroupId);
  return group === undefined ? !record.settled : group || !record.settled;
};

const waitForStopped = async (records, timeout) => {
  const deadline = Date.now() + timeout;
  while (records.some(recordIsRunning)) {
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, STOP_POLL_INTERVAL));
  }
  return true;
};

export class PreparationProcessOwner {
  #children = new Map();
  #spawn;
  #stopping = false;
  #stopPromise;

  constructor({ spawn = defaultSpawn } = {}) {
    this.#spawn = spawn;
  }

  requireActive() {
    if (this.#stopping) throw new PreparationCancelled();
  }

  async run(label, command, args, options = {}) {
    this.requireActive();
    const child = this.#spawn(command, args, {
      ...options,
      detached: options.detached ?? process.platform !== "win32",
    });
    const record = {
      processGroupId: child.pid,
      settled: false,
    };
    const completion = new Promise((resolve, reject) => {
      let completed = false;
      const finish = (outcome) => {
        if (completed) return;
        completed = true;
        record.settled = true;
        outcome(resolve, reject);
      };
      child.once("error", (error) => finish((_resolve, rejectError) => rejectError(error)));
      child.once("exit", (code, signal) =>
        finish((resolveExit, rejectExit) => {
          if (this.#stopping) {
            rejectExit(new PreparationCancelled());
          } else if (code === 0 && signal === null) {
            resolveExit();
          } else {
            rejectExit(new Error(`${label} exited with ${code ?? signal}`));
          }
        }),
      );
    });
    this.#children.set(child, record);
    let operationError;
    try {
      await completion;
    } catch (error) {
      operationError = error;
    }
    let cleanupError;
    try {
      if (this.#stopping) {
        await this.#stopPromise;
      } else {
        await this.#stopRecords([record], "SIGTERM", DEFAULT_STOP_TIMEOUT);
      }
    } catch (error) {
      cleanupError = error;
    } finally {
      this.#children.delete(child);
    }
    if (cleanupError !== undefined) {
      if (operationError !== undefined) {
        if (operationError instanceof PreparationCancelled) {
          throw new PreparationCancelled({ cause: cleanupError });
        }
        throw new Error(cleanupError.message, { cause: operationError });
      }
      throw cleanupError;
    }
    if (operationError !== undefined) throw operationError;
  }

  stop(signal = "SIGTERM", timeout = DEFAULT_STOP_TIMEOUT) {
    if (this.#stopPromise !== undefined) return this.#stopPromise;
    this.#stopping = true;
    this.#stopPromise = this.#stopRecords([...this.#children.values()], signal, timeout);
    return this.#stopPromise;
  }

  async #stopRecords(records, signal, timeout) {
    const running = records.filter(recordIsRunning);
    running.forEach((record) => stopProcessGroup(record.processGroupId, signal));
    if (await waitForStopped(running, timeout)) return;
    running.forEach((record) => stopProcessGroup(record.processGroupId, "SIGKILL"));
    if (!(await waitForStopped(running, timeout))) {
      throw new Error("E2E preparation process group survived shutdown");
    }
  }
}
