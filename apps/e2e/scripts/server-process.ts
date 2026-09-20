import type { ChildProcess } from "node:child_process";
import type { Readable, Writable } from "node:stream";

import { finished } from "node:stream/promises";

import type { E2EEndpoint } from "./network.ts";

import { requestStudioShutdown } from "./graceful-shutdown.ts";
import { unregisterNotebookProcess } from "./notebook-process-registry.ts";
import { portIsOpen, processGroupIsRunning, stopProcessGroup } from "./process-group.ts";
import {
  startRegisteredNotebookProcess,
  type SupervisorOptions,
} from "./registered-notebook-process.ts";

export interface ProcessOutput {
  stdout?: Writable;
  stderr?: Writable;
}
export interface StopOptions {
  signal?: NodeJS.Signals;
  timeout?: number;
}
interface OwnedProcess {
  child: ChildProcess;
  port: number | null;
  processGroupId?: number;
  serverUrl: string;
  authToken?: string;
  studioEntry?: string;
  output?: () => string;
}
export interface ServerOptions extends Omit<SupervisorOptions, "port"> {
  endpoint: E2EEndpoint;
  forward?: ProcessOutput;
  shutdown: "studio" | "process";
  serverUrl?: string;
  authToken?: string;
  studioEntry?: string;
}

interface ReadinessOptions {
  timeout?: number;
  output?: () => string;
  request?: typeof fetch;
}

const REQUEST_TIMEOUT = 500;
const LEAKED_SEMAPHORE_WARNING =
  /resource_tracker:\s*There appear to be \d+ leaked semaphore objects? to clean up at shutdown/;

export const assertNoLeakedSemaphoreWarning = (output: string) => {
  const warning = output.match(LEAKED_SEMAPHORE_WARNING)?.[0];
  if (warning) {
    throw new Error("Notebook server leaked semaphore objects during shutdown\n" + warning);
  }
};

const captureProcessOutput = (child: ChildProcess, { stdout, stderr }: ProcessOutput = {}) => {
  let output = "";
  const capture = (stream: Readable | null, forward?: Writable) => {
    stream?.on("data", (chunk) => {
      output += chunk.toString();
      forward?.write(chunk);
    });
  };
  capture(child.stdout, stdout);
  capture(child.stderr, stderr);
  return () => output;
};

export const waitForServer = async (
  child: Pick<ChildProcess, "exitCode" | "signalCode">,
  url: string,
  { timeout = 60_000, output = () => String(), request = fetch }: ReadinessOptions = {},
) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      const status =
        child.signalCode !== null ? "signal " + child.signalCode : "status " + child.exitCode;
      throw new Error(url + " exited during startup with " + status + "\n" + output());
    }
    try {
      const response = await request(url, {
        signal: AbortSignal.timeout(Math.max(1, Math.min(REQUEST_TIMEOUT, deadline - Date.now()))),
      });
      await response.body?.cancel();
      if (response.ok) return;
    } catch {
      // The socket is unavailable until the server starts listening.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(url + " did not start\n" + output());
};

const waitForStop = async (
  { child, port, processGroupId }: Pick<OwnedProcess, "child" | "port" | "processGroupId">,
  timeout: number,
) => {
  const deadline = Date.now() + timeout;
  do {
    const processTreeRunning =
      processGroupId === undefined
        ? child.pid !== undefined && child.exitCode === null && child.signalCode === null
        : (processGroupIsRunning(processGroupId) ??
          (child.exitCode === null && child.signalCode === null));
    if (!processTreeRunning && !(await portIsOpen(port))) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  } while (Date.now() < deadline);
  return false;
};

const childClose = async (child: ChildProcess) => {
  const exited =
    child.pid === undefined || child.exitCode !== null || child.signalCode !== null
      ? Promise.resolve()
      : new Promise<void>((resolve) => {
          child.once("exit", () => resolve());
          child.once("error", () => resolve());
        });
  const streams = [child.stdout, child.stderr].filter(
    (stream): stream is Readable => stream !== null,
  );
  await Promise.all([
    exited,
    ...streams.map((stream) =>
      stream.destroyed || stream.readableEnded
        ? Promise.resolve()
        : finished(stream, { cleanup: true, writable: false }),
    ),
  ]);
};

const waitForClose = async (closed: Promise<void>, timeout: number) => {
  let timer: NodeJS.Timeout | undefined;
  const timedOut = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("Notebook server stdio did not close")), timeout);
  });
  try {
    await Promise.race([closed, timedOut]);
  } finally {
    clearTimeout(timer);
  }
};

export const verifyNotebookProcessOutput = async (
  closed: Promise<void>,
  output: () => string,
  timeout = 5_000,
) => {
  await waitForClose(closed, timeout);
  assertNoLeakedSemaphoreWarning(output());
};

export const stopNotebookProcess = async (
  {
    authToken = "",
    child,
    output = () => String(),
    port,
    processGroupId = child.pid,
    serverUrl,
    studioEntry = "",
  }: OwnedProcess,
  {
    shutdown,
    signal = "SIGTERM",
    timeout = 5_000,
  }: StopOptions & { shutdown: "studio" | "process" },
) => {
  const target = processGroupId ?? child.pid;
  const closed = childClose(child);
  let shutdownError: unknown;
  const finish = async () => {
    let outputError;
    try {
      await verifyNotebookProcessOutput(closed, output, timeout);
    } catch (error) {
      outputError = error;
    }
    if (shutdownError && outputError) {
      throw new AggregateError(
        [shutdownError, outputError],
        `Notebook graceful shutdown and output verification failed: ${shutdownError instanceof Error ? shutdownError.message : "unknown failure"}`,
      );
    }
    if (shutdownError) throw shutdownError;
    if (outputError) throw outputError;
  };
  let stopped = false;
  if (shutdown === "studio" && port !== null) {
    try {
      await requestStudioShutdown(serverUrl, authToken, timeout, studioEntry);
      stopped = await waitForStop({ child, port, processGroupId }, timeout);
    } catch (error) {
      shutdownError = error;
    }
  }
  if (stopped) {
    await finish();
    return;
  }
  stopProcessGroup(target, signal);
  if (await waitForStop({ child, port, processGroupId }, timeout)) {
    await finish();
    return;
  }
  stopProcessGroup(target, "SIGKILL");
  if (!(await waitForStop({ child, port, processGroupId }, timeout))) {
    throw new Error(
      "Notebook server process tree or port " + port + " survived shutdown\n" + output(),
    );
  }
  await finish();
};

export class ServerHandle {
  readonly child: ChildProcess;
  readonly processGroupId: number | undefined;
  readonly ready: Promise<void>;
  readonly exited: Promise<Error>;
  readonly serverUrl: string;
  readonly output: () => string;
  readonly #options: ServerOptions;
  readonly #ownerNonce: string;
  #port: number | null = null;
  #releaseRoute: (() => void) | undefined;
  #closing: Promise<void> | undefined;
  #failure: Error | undefined;

  constructor(options: ServerOptions) {
    const origin = options.endpoint.origin;
    this.#options = options;
    this.serverUrl = options.serverUrl ?? origin;
    const registration = startRegisteredNotebookProcess({ ...options, port: null });
    this.child = registration.child;
    this.processGroupId = registration.processGroupId;
    this.#ownerNonce = registration.ownerNonce;
    this.output = captureProcessOutput(this.child, options.forward);
    this.exited = new Promise((resolveExit) => {
      const fail = (error: Error) => {
        if (!this.#closing) this.#failure ??= error;
        this.#releaseRoute?.();
        resolveExit(error);
      };
      this.child.once("error", fail);
      this.child.once("exit", (code, signal) =>
        fail(
          new Error(
            `Notebook service exited unexpectedly with ${signal ?? code}\n${this.output()}`,
          ),
        ),
      );
    });
    this.ready = Promise.all([registration.ready, registration.bound]).then(([, port]) => {
      this.#port = port;
      if (this.#closing || this.#failure)
        throw new Error("Notebook service closed before binding its route");
      this.#releaseRoute = options.endpoint.bindBackend(port);
    });
    void this.ready.catch(() => undefined);
  }

  get port() {
    return this.#port;
  }

  async waitUntilReady(url = this.serverUrl, { timeout }: StopOptions = {}): Promise<void> {
    await this.ready.catch((error) => {
      throw new Error(`Notebook process registration failed: ${String(error)}\n${this.output()}`);
    });
    await waitForServer(this.child, url, { output: this.output, timeout });
  }

  close(options: StopOptions = {}): Promise<void> {
    this.#closing ??= Promise.resolve().then(() => this.#close(options));
    return this.#closing;
  }

  async #close(options: StopOptions): Promise<void> {
    const errors: unknown[] = this.#failure ? [this.#failure] : [];
    try {
      await stopNotebookProcess(
        {
          ...this.#options,
          child: this.child,
          port: this.port,
          processGroupId: this.processGroupId,
          serverUrl: this.serverUrl,
          output: this.output,
        },
        { ...options, shutdown: this.#options.shutdown },
      );
    } catch (error) {
      errors.push(error);
    } finally {
      this.#releaseRoute?.();
      if (
        this.processGroupId !== undefined &&
        (processGroupIsRunning(this.processGroupId) ??
          (this.child.exitCode === null && this.child.signalCode === null)) === false
      ) {
        unregisterNotebookProcess(
          { ownerNonce: this.#ownerNonce, processGroupId: this.processGroupId },
          { directory: this.#options.directory },
        );
      }
    }
    if (errors.length === 1) throw errors[0];
    if (errors.length) throw new AggregateError(errors, "Notebook service shutdown failed");
  }
}
