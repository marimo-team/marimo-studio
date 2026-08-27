import { connect } from "node:net";

import { requestStudioShutdown } from "./graceful-shutdown.mjs";
import { processGroupIsRunning, stopProcessGroup } from "./process-group.mjs";

const REQUEST_TIMEOUT = 500;
const LEAKED_SEMAPHORE_WARNING =
  /resource_tracker:\s*There appear to be \d+ leaked semaphore objects? to clean up at shutdown/;

export const assertNoLeakedSemaphoreWarning = (output) => {
  const warning = output.match(LEAKED_SEMAPHORE_WARNING)?.[0];
  if (warning) {
    throw new Error("Notebook server leaked semaphore objects during shutdown\n" + warning);
  }
};

export const captureProcessOutput = (child, { stdout, stderr } = {}) => {
  let output = "";
  const capture = (stream, forward) => {
    stream?.on("data", (chunk) => {
      output += chunk.toString();
      forward?.write(chunk);
    });
  };
  capture(child.stdout, stdout);
  capture(child.stderr, stderr);
  return () => output;
};

const portIsOpen = (port) =>
  new Promise((resolve) => {
    const socket = connect({ host: "127.0.0.1", port });
    const finish = (open) => {
      socket.destroy();
      resolve(open);
    };
    socket.setTimeout(100, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });

export const waitForServer = async (
  child,
  url,
  { timeout = 60_000, output = () => String(), request = fetch } = {},
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

const waitForStop = async ({ child, port, processGroupId }, timeout) => {
  const deadline = Date.now() + timeout;
  do {
    const processTreeRunning =
      processGroupId === undefined
        ? child.exitCode === null && child.signalCode === null
        : (processGroupIsRunning(processGroupId) ??
          (child.exitCode === null && child.signalCode === null));
    if (!processTreeRunning && !(await portIsOpen(port))) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  } while (Date.now() < deadline);
  return false;
};

const childClose = (child) => {
  const streams = [child.stdout, child.stderr].filter(Boolean);
  const exited = child.exitCode !== null || child.signalCode !== null;
  if (exited && streams.every((stream) => stream.destroyed || stream.readableEnded)) {
    return Promise.resolve();
  }
  return new Promise((resolve) => child.once("close", resolve));
};

const waitForClose = async (closed, timeout) => {
  let timer;
  const timedOut = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("Notebook server stdio did not close")), timeout);
  });
  try {
    await Promise.race([closed, timedOut]);
  } finally {
    clearTimeout(timer);
  }
};

export const verifyNotebookProcessOutput = async (closed, output, timeout = 5_000) => {
  await waitForClose(closed, timeout);
  assertNoLeakedSemaphoreWarning(output());
};

export const stopNotebookProcess = async (
  { authToken = "", child, output = () => String(), port, processGroupId = child.pid, serverUrl },
  { shutdown, signal = "SIGTERM", timeout = 5_000 },
) => {
  if (shutdown !== "studio" && shutdown !== "run" && shutdown !== "process") {
    throw new TypeError(`Unknown server shutdown mode ${shutdown}`);
  }
  const target = processGroupId ?? child.pid;
  const closed = childClose(child);
  let shutdownError;
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
        `Notebook graceful shutdown and output verification failed: ${String(shutdownError)}`,
      );
    }
    if (shutdownError) throw shutdownError;
    if (outputError) throw outputError;
  };
  let stopped = false;
  if (shutdown === "studio") {
    try {
      await requestStudioShutdown(serverUrl, authToken, Math.min(timeout, 5_000));
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
