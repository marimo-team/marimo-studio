import { spawn as spawnChild } from "node:child_process";
import { randomBytes } from "node:crypto";

import {
  processGroupIsRunning,
  processGroupOwnerState,
  stopProcessGroup,
} from "./process-group.mjs";

const DEFAULT_STOP_TIMEOUT = 5_000;
const DEFAULT_LEADER_STOP_TIMEOUT = 15_000;
const STOP_POLL_INTERVAL = 50;
const DEFAULT_CAPTURE_LIMIT = 1024 * 1024;
const PREPARATION_PROCESS_OWNER_ENV = "MARIMO_STUDIO_E2E_PREPARATION_PROCESS_OWNER";
/** @type {(command: string, args: string[], options: import("node:child_process").SpawnOptions) => import("node:child_process").ChildProcess} */
const defaultSpawn = spawnChild;

export class PreparationCancelled extends Error {
  constructor(options) {
    super("E2E preparation was cancelled", options);
    this.name = "PreparationCancelled";
  }
}

const waitUntil = async (condition, timeout) => {
  const deadline = Date.now() + timeout;
  while (!condition()) {
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, STOP_POLL_INTERVAL));
  }
  return true;
};

class OwnedProcess {
  #cancelled = false;
  #capture;
  #child;
  #completion;
  #forcedError;
  #label;
  #ownerNonce = randomBytes(32).toString("hex");
  #processGroupId;
  #settled = false;
  #stderrBytes = 0;
  #stderrChunks = [];
  #stdoutBytes = 0;
  #stdoutChunks = [];
  #stopPromise;
  #timer;

  constructor({ spawn, label, command, args, options, capture }) {
    this.#capture = capture;
    this.#label = label;
    this.#child = spawn(command, args, {
      ...options,
      detached: options.detached ?? process.platform !== "win32",
      env: {
        ...(options.env ?? process.env),
        [PREPARATION_PROCESS_OWNER_ENV]: this.#ownerNonce,
      },
    });
    this.#processGroupId = this.#child.pid;
    this.#captureStream(this.#child.stdout, "stdout");
    this.#captureStream(this.#child.stderr, "stderr");
    this.#completion = this.#observeCompletion();
    if (capture?.timeout !== undefined) {
      this.#timer = setTimeout(
        () => this.#failAndStop(new Error(`${label} exceeded ${capture.timeout}ms`)),
        capture.timeout,
      );
    }
  }

  async result() {
    let operationError;
    try {
      await this.#completion;
    } catch (error) {
      operationError = error;
    } finally {
      clearTimeout(this.#timer);
    }

    let cleanupError;
    try {
      await (this.#stopPromise ?? this.#terminate("SIGTERM", DEFAULT_STOP_TIMEOUT));
    } catch (error) {
      cleanupError = error;
    }
    if (cleanupError !== undefined) {
      if (operationError instanceof PreparationCancelled) {
        throw new PreparationCancelled({ cause: cleanupError });
      }
      if (operationError !== undefined) {
        throw new Error(cleanupError.message, { cause: operationError });
      }
      throw cleanupError;
    }
    if (operationError !== undefined) throw operationError;
    return Object.freeze(this.#output());
  }

  cancel(signal, timeout) {
    this.#cancelled = true;
    return this.#terminate(signal, timeout);
  }

  cancelLeaders(signal, leaderTimeout, fallbackTimeout) {
    this.#cancelled = true;
    if (this.#stopPromise === undefined) {
      this.#stopPromise = this.#stopLeader(signal, leaderTimeout, fallbackTimeout);
    }
    return this.#stopPromise;
  }

  #captureStream(stream, name) {
    if (this.#capture === undefined) return;
    stream?.on("data", (chunk) => {
      if (this.#forcedError !== undefined) return;
      const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      const bytes = name === "stdout" ? this.#stdoutBytes : this.#stderrBytes;
      if (bytes + value.byteLength > this.#capture.maxBuffer) {
        this.#failAndStop(
          new Error(`${this.#label} ${name} exceeded ${this.#capture.maxBuffer} bytes`),
        );
        return;
      }
      if (name === "stdout") {
        this.#stdoutChunks.push(value);
        this.#stdoutBytes += value.byteLength;
      } else {
        this.#stderrChunks.push(value);
        this.#stderrBytes += value.byteLength;
      }
    });
  }

  #failAndStop(error) {
    if (this.#forcedError !== undefined) return;
    this.#forcedError = error;
    void this.#terminate("SIGTERM", DEFAULT_STOP_TIMEOUT).catch(() => undefined);
  }

  #observeCompletion() {
    return new Promise((resolve, reject) => {
      let completed = false;
      const finish = (outcome) => {
        if (completed) return;
        completed = true;
        this.#settled = true;
        outcome(resolve, reject);
      };
      this.#child.once("error", (error) => finish((_resolve, rejectError) => rejectError(error)));
      this.#child.once(this.#capture === undefined ? "exit" : "close", (code, signal) => {
        finish((resolveExit, rejectExit) => {
          const output = this.#output();
          if (this.#forcedError !== undefined) {
            Object.assign(this.#forcedError, output);
            rejectExit(this.#forcedError);
          } else if (this.#cancelled) {
            rejectExit(new PreparationCancelled());
          } else if (code === 0 && signal === null) {
            resolveExit();
          } else {
            const detail = output.stderr || output.stdout;
            const error = new Error(
              `${this.#label} exited with ${code ?? signal}${detail ? `\n${detail}` : ""}`,
            );
            Object.assign(error, { code, signal, ...output });
            rejectExit(error);
          }
        });
      });
    });
  }

  #output() {
    return {
      stderr: Buffer.concat(this.#stderrChunks).toString(),
      stdout: Buffer.concat(this.#stdoutChunks).toString(),
    };
  }

  #ownerState() {
    if (this.#processGroupId === undefined) return this.#settled ? "stopped" : "owned";
    const running = processGroupIsRunning(this.#processGroupId);
    if (running === false) return "stopped";
    if (process.platform === "win32") {
      return running === undefined && this.#settled ? "stopped" : "owned";
    }
    return processGroupOwnerState(
      this.#processGroupId,
      PREPARATION_PROCESS_OWNER_ENV,
      this.#ownerNonce,
    );
  }

  #signalGroup(signal) {
    const state = this.#ownerState();
    if (state === "unknown") {
      throw new Error("E2E preparation process group ownership could not be verified");
    }
    if (state !== "owned") return false;
    stopProcessGroup(this.#processGroupId, signal);
    return true;
  }

  #signalLeader(signal) {
    const state = this.#ownerState();
    if (state === "unknown") {
      throw new Error("E2E preparation process group ownership could not be verified");
    }
    if (state !== "owned") return false;
    try {
      this.#child.kill(signal);
    } catch (error) {
      if (error?.code !== "ESRCH") throw error;
    }
    return true;
  }

  #isRunning() {
    const state = this.#ownerState();
    return state === "owned" || state === "unknown";
  }

  #terminate(signal, timeout) {
    if (this.#stopPromise === undefined) {
      this.#stopPromise = this.#stopGroup(signal, timeout);
    }
    return this.#stopPromise;
  }

  async #stopLeader(signal, leaderTimeout, fallbackTimeout) {
    if (!this.#signalLeader(signal)) return;
    await waitUntil(() => this.#settled, leaderTimeout);
    await this.#stopGroup(signal, fallbackTimeout);
  }

  async #stopGroup(signal, timeout) {
    if (!this.#signalGroup(signal)) return;
    if (await waitUntil(() => !this.#isRunning(), timeout)) return;
    if (!this.#signalGroup("SIGKILL")) return;
    if (!(await waitUntil(() => !this.#isRunning(), timeout))) {
      throw new Error("E2E preparation process group survived shutdown");
    }
  }
}

export class PreparationProcessOwner {
  #processes = new Set();
  #spawn;
  #stopping = false;
  #stopPromise;

  constructor({ spawn = defaultSpawn } = {}) {
    this.#spawn = spawn;
  }

  requireActive() {
    if (this.#stopping) throw new PreparationCancelled();
  }

  run(label, command, args, options = {}) {
    return this.#run(label, command, args, options).then(() => undefined);
  }

  /**
   * @param {string} label
   * @param {string} command
   * @param {string[]} args
   * @param {import("node:child_process").SpawnOptions} [options]
   * @param {{ maxBuffer?: number, timeout?: number }} [captureOptions]
   * @returns {Promise<Readonly<{ stderr: string, stdout: string }>>}
   */
  runCaptured(label, command, args, options = {}, captureOptions = {}) {
    const { maxBuffer = DEFAULT_CAPTURE_LIMIT, timeout } = captureOptions;
    if (!Number.isSafeInteger(maxBuffer) || maxBuffer <= 0) {
      throw new RangeError("Captured process output limit must be a positive integer");
    }
    if (timeout !== undefined && (!Number.isSafeInteger(timeout) || timeout <= 0)) {
      throw new RangeError("Captured process timeout must be a positive integer");
    }
    return this.#run(
      label,
      command,
      args,
      { ...options, stdio: options.stdio ?? ["ignore", "pipe", "pipe"] },
      { maxBuffer, timeout },
    );
  }

  async #run(label, command, args, options, capture) {
    this.requireActive();
    const owned = new OwnedProcess({
      args,
      capture,
      command,
      label,
      options,
      spawn: this.#spawn,
    });
    this.#processes.add(owned);
    try {
      return await owned.result();
    } finally {
      this.#processes.delete(owned);
    }
  }

  stop(signal = "SIGTERM", timeout = DEFAULT_STOP_TIMEOUT) {
    if (this.#stopPromise !== undefined) return this.#stopPromise;
    this.#stopping = true;
    this.#stopPromise = Promise.all(
      [...this.#processes].map((owned) => owned.cancel(signal, timeout)),
    ).then(() => undefined);
    return this.#stopPromise;
  }

  stopLeaders(
    signal = "SIGTERM",
    leaderTimeout = DEFAULT_LEADER_STOP_TIMEOUT,
    fallbackTimeout = DEFAULT_STOP_TIMEOUT,
  ) {
    if (this.#stopPromise !== undefined) return this.#stopPromise;
    this.#stopping = true;
    this.#stopPromise = Promise.all(
      [...this.#processes].map((owned) =>
        owned.cancelLeaders(signal, leaderTimeout, fallbackTimeout),
      ),
    ).then(() => undefined);
    return this.#stopPromise;
  }
}
