import type { ChildProcess, Serializable } from "node:child_process";
import type { Readable, Writable } from "node:stream";

import { constants } from "node:os";
import { finished } from "node:stream/promises";

import type { E2EEndpoint } from "./network.ts";

import { requestStudioShutdown } from "./graceful-shutdown.ts";
import { unregisterNotebookProcess } from "./notebook-process-registry.ts";
import { portIsOpen, processGroupIsRunning, stopProcessGroup } from "./process-group.ts";
import {
  startRegisteredNotebookProcess,
  supervisorMessageSchema,
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
  onSignal?: (signal: NodeJS.Signals) => void;
}
export interface ServerOptions extends SupervisorOptions {
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

const captureProcessOutput = (
  child: ChildProcess,
  fail: (error: Error) => void,
  { stdout, stderr }: ProcessOutput = {},
) => {
  let output = "";
  let pendingWrites = 0;
  let finishing = false;
  const drained = Promise.withResolvers<void>();
  const destinations = new Set([stdout, stderr].filter((stream) => stream !== undefined));
  for (const destination of destinations) destination.on("error", fail);
  const finish = () => {
    if (!finishing || pendingWrites !== 0) return;
    for (const destination of destinations) destination.off("error", fail);
    drained.resolve();
  };
  const capture = (stream: Readable | null, forward?: Writable) => {
    stream?.on("error", fail);
    stream?.on("data", (chunk) => {
      output += chunk.toString();
      if (finishing || !forward) return;
      pendingWrites += 1;
      let settled = false;
      const written = (error?: Error | null) => {
        if (settled) return;
        settled = true;
        if (error) fail(error);
        // Writable emits a failed write's error after invoking its callback.
        setImmediate(() => {
          pendingWrites -= 1;
          finish();
        });
      };
      try {
        forward.write(chunk, written);
      } catch (error) {
        written(
          error instanceof Error
            ? error
            : new Error("Notebook output forwarding failed", { cause: error }),
        );
      }
    });
  };
  capture(child.stdout, stdout);
  capture(child.stderr, stderr);
  return {
    output: () => output,
    finish: () => {
      finishing = true;
      finish();
      return drained.promise;
    },
  };
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

const waitForClose = async (
  closed: Promise<void>,
  timeout: number,
  message = "Notebook server stdio did not close",
) => {
  let timer: NodeJS.Timeout | undefined;
  const timedOut = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), timeout);
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
    onSignal,
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
  onSignal?.(signal === "SIGINT" ? "SIGTERM" : signal);
  stopProcessGroup(target, signal);
  if (await waitForStop({ child, port, processGroupId }, timeout)) {
    await finish();
    return;
  }
  onSignal?.("SIGKILL");
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
  readonly #finishOutput: () => Promise<void>;
  #port: number | null = null;
  #releaseRoute: (() => void) | undefined;
  #closing: Promise<void> | undefined;
  #failure: Error | undefined;
  #stopSignals = new Set<NodeJS.Signals>();

  constructor(options: ServerOptions) {
    const origin = options.endpoint.origin;
    this.#options = options;
    this.serverUrl = options.serverUrl ?? origin;
    const registration = startRegisteredNotebookProcess(options);
    this.child = registration.child;
    this.processGroupId = registration.processGroupId;
    this.#ownerNonce = registration.ownerNonce;
    const exited = Promise.withResolvers<Error>();
    this.exited = exited.promise;
    const resolveExit = exited.resolve;
    const fail = (error: Error) => {
      this.#failure ??= error;
      resolveExit(error);
    };
    const capture = captureProcessOutput(this.child, fail, options.forward);
    this.output = capture.output;
    const onMessage = (source: Serializable) => {
      const message = supervisorMessageSchema.safeParse(source);
      if (message.success && message.data.type === "failed") {
        const exit = message.data.exit;
        if (this.#closing && exit && this.#expectedExit(exit.code, exit.signal)) return;
        fail(new Error(`${message.data.message}\n${this.output()}`));
      }
    };
    this.#finishOutput = () => {
      this.child.off("message", onMessage);
      return capture.finish();
    };
    this.child.on("message", onMessage);
    this.child.once("error", fail);
    this.child.once("exit", (code, signal) => {
      this.child.off("message", onMessage);
      this.#releaseRoute?.();
      const error = new Error(
        `Notebook service exited unexpectedly with ${signal ?? code}\n${this.output()}`,
      );
      if (!this.#closing || !this.#expectedExit(code, signal)) {
        fail(error);
      } else {
        resolveExit(error);
      }
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

  #expectedExit(code: number | null, signal: string | null): boolean {
    return (
      code === 0 ||
      [...this.#stopSignals].some(
        (sent) =>
          signal === sent ||
          code === 128 + constants.signals[sent] ||
          (process.platform === "win32" && sent === "SIGKILL" && code === 1),
      )
    );
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
    const errors: unknown[] = [];
    try {
      await stopNotebookProcess(
        {
          ...this.#options,
          child: this.child,
          port: this.port,
          processGroupId: this.processGroupId,
          serverUrl: this.serverUrl,
          output: this.output,
          onSignal: (signal) => this.#stopSignals.add(signal),
        },
        { ...options, shutdown: this.#options.shutdown },
      );
    } catch (error) {
      errors.push(error);
    } finally {
      try {
        await waitForClose(
          this.#finishOutput(),
          options.timeout ?? 5_000,
          "Notebook forwarded output did not finish",
        );
      } catch (error) {
        errors.push(error);
      }
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
    if (this.#failure) errors.unshift(this.#failure);
    if (errors.length === 1) throw errors[0];
    if (errors.length) throw new AggregateError(errors, "Notebook service shutdown failed");
  }
}
