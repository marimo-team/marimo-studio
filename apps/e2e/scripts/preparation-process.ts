import type { ChildProcess, SpawnOptions } from "node:child_process";
import type { Readable } from "node:stream";

import { spawn as spawnChild } from "node:child_process";
import { randomBytes } from "node:crypto";

import {
  processGroupIsRunning,
  processGroupOwnerState,
  stopProcessGroup,
} from "./process-group.ts";

const DEFAULT_STOP_TIMEOUT = 5_000;
const STOP_POLL_INTERVAL = 50;
const DEFAULT_CAPTURE_LIMIT = 1024 * 1024;
const PREPARATION_PROCESS_OWNER_ENV = "MARIMO_STUDIO_E2E_PREPARATION_PROCESS_OWNER";
type Spawn = (command: string, args: string[], options: SpawnOptions) => ChildProcess;
interface OwnerOptions {
  spawn?: Spawn;
}
interface CaptureOptions {
  maxBuffer: number;
  timeout?: number;
}
interface ProcessOptions {
  spawn: Spawn;
  label: string;
  command: string;
  args: string[];
  options: SpawnOptions;
  capture?: CaptureOptions;
}

export class PreparationCancelled extends Error {
  constructor(options?: ErrorOptions) {
    super("E2E preparation was cancelled", options);
    this.name = "PreparationCancelled";
  }
}

const waitUntil = async (condition: () => boolean, timeout: number) => {
  const deadline = Date.now() + timeout;
  while (!condition()) {
    if (Date.now() >= deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, STOP_POLL_INTERVAL));
  }
  return true;
};

class OwnedProcess {
  #cancelled = false;
  #capture: CaptureOptions | undefined;
  #child: ChildProcess;
  #completion: Promise<void>;
  #forcedError: Error | undefined;
  #label: string;
  #ownerNonce = randomBytes(32).toString("hex");
  #processGroupId: number | undefined;
  #settled = false;
  #stderrBytes = 0;
  #stderrChunks: Buffer[] = [];
  #stdoutBytes = 0;
  #stdoutChunks: Buffer[] = [];
  #stopPromise: Promise<void> | undefined;
  #timer: ReturnType<typeof setTimeout> | undefined;

  constructor({ spawn, label, command, args, options, capture }: ProcessOptions) {
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
    let operationError: unknown;
    try {
      await this.#completion;
    } catch (error) {
      operationError = error;
    } finally {
      clearTimeout(this.#timer);
    }

    let cleanupError: unknown;
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
        throw new AggregateError(
          [operationError, cleanupError],
          "E2E preparation and cleanup failed",
        );
      }
      throw cleanupError;
    }
    if (operationError !== undefined) throw operationError;
    return Object.freeze(this.#output());
  }

  cancel(signal: NodeJS.Signals, timeout: number) {
    this.#cancelled = true;
    return this.#terminate(signal, timeout);
  }

  #captureStream(stream: Readable | null, name: "stdout" | "stderr") {
    const capture = this.#capture;
    if (capture === undefined) return;
    stream?.on("data", (chunk: Buffer | string) => {
      if (this.#forcedError !== undefined) return;
      const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      const bytes = name === "stdout" ? this.#stdoutBytes : this.#stderrBytes;
      if (bytes + value.byteLength > capture.maxBuffer) {
        this.#failAndStop(new Error(`${this.#label} ${name} exceeded ${capture.maxBuffer} bytes`));
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

  #failAndStop(error: Error) {
    if (this.#forcedError !== undefined) return;
    this.#forcedError = error;
    void this.#terminate("SIGTERM", DEFAULT_STOP_TIMEOUT).catch(() => undefined);
  }

  #observeCompletion() {
    return new Promise<void>((resolve, reject) => {
      let completed = false;
      const finish = (outcome: () => void) => {
        if (completed) return;
        completed = true;
        this.#settled = true;
        outcome();
      };
      this.#child.once("error", (error) => finish(() => reject(error)));
      this.#child.once(this.#capture === undefined ? "exit" : "close", (code, signal) => {
        finish(() => {
          const output = this.#output();
          if (this.#forcedError !== undefined) {
            Object.assign(this.#forcedError, output);
            reject(this.#forcedError);
          } else if (this.#cancelled) {
            reject(new PreparationCancelled());
          } else if (code === 0 && signal === null) {
            resolve();
          } else {
            const detail = output.stderr || output.stdout;
            const error = new Error(
              `${this.#label} exited with ${code ?? signal}${detail ? `\n${detail}` : ""}`,
            );
            Object.assign(error, { code, signal, ...output });
            reject(error);
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

  #signalGroup(signal: NodeJS.Signals) {
    const state = this.#ownerState();
    if (state === "unknown") {
      throw new Error("E2E preparation process group ownership could not be verified");
    }
    if (state !== "owned") return false;
    stopProcessGroup(this.#processGroupId, signal);
    return true;
  }

  #isRunning() {
    const state = this.#ownerState();
    return state === "owned" || state === "unknown";
  }

  #terminate(signal: NodeJS.Signals, timeout: number) {
    if (this.#stopPromise === undefined) {
      this.#stopPromise = this.#stopGroup(signal, timeout);
    }
    return this.#stopPromise;
  }

  async #stopGroup(signal: NodeJS.Signals, timeout: number) {
    if (!this.#signalGroup(signal)) return;
    if (await waitUntil(() => !this.#isRunning(), timeout)) return;
    if (!this.#signalGroup("SIGKILL")) return;
    if (!(await waitUntil(() => !this.#isRunning(), timeout))) {
      throw new Error("E2E preparation process group survived shutdown");
    }
  }
}

export class PreparationProcessOwner {
  #processes = new Set<OwnedProcess>();
  #spawn: Spawn;
  #stopping = false;
  #stopPromise: Promise<void> | undefined;

  constructor({ spawn = spawnChild }: OwnerOptions = {}) {
    this.#spawn = spawn;
  }

  requireActive() {
    if (this.#stopping) throw new PreparationCancelled();
  }

  run(label: string, command: string, args: string[], options: SpawnOptions = {}) {
    return this.#run(label, command, args, options).then(() => undefined);
  }

  runCaptured(
    label: string,
    command: string,
    args: string[],
    options: SpawnOptions = {},
    captureOptions: Partial<CaptureOptions> = {},
  ) {
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

  async #run(
    label: string,
    command: string,
    args: string[],
    options: SpawnOptions,
    capture?: CaptureOptions,
  ) {
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

  stop(signal: NodeJS.Signals = "SIGTERM", timeout = DEFAULT_STOP_TIMEOUT) {
    if (this.#stopPromise !== undefined) return this.#stopPromise;
    this.#stopping = true;
    this.#stopPromise = Promise.all(
      [...this.#processes].map((owned) => owned.cancel(signal, timeout)),
    ).then(() => undefined);
    return this.#stopPromise;
  }
}
