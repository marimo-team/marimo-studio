import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync, watch, type FSWatcher } from "node:fs";
import { z } from "zod";

import type { SupervisorMessage } from "./registered-notebook-process.ts";

import {
  NOTEBOOK_PROCESS_OWNER_ENV,
  NOTEBOOK_PROCESS_ENDPOINT_ENV,
  NOTEBOOK_PROCESS_REGISTRY_ENV,
  registerNotebookProcess,
  notebookProcessEndpointPath,
  removeNotebookEndpointReceipt,
  unregisterNotebookProcess,
} from "./notebook-process-registry.ts";
import {
  liveProcessGroupMembers,
  portIsOpen,
  processEnvironmentContains,
  stopProcessGroup,
} from "./process-group.ts";

const FORCE_STOP_DELAY = 5_000;
const PORT_CLOSE_TIMEOUT = 5_000;
const PORT_POLL_INTERVAL = 50;
const command = process.argv[2] ?? "";
const args = process.argv.slice(3);
const directory = process.env[NOTEBOOK_PROCESS_REGISTRY_ENV] ?? "";
const ownerNonce = process.env[NOTEBOOK_PROCESS_OWNER_ENV] ?? "";
let port: number | null = null;
const processGroupId = process.pid;

if (!command || !directory || !ownerNonce) {
  throw new Error("Notebook process supervisor received an invalid registration");
}

registerNotebookProcess({ ownerNonce, port, processGroupId }, { directory });

const endpointPath = notebookProcessEndpointPath(directory, processGroupId, ownerNonce);
const endpointSchema = z
  .object({
    ownerNonce: z.literal(ownerNonce),
    pid: z.number().int().positive().safe(),
    port: z.number().int().positive().max(65_535),
  })
  .strict();
const childEnvironment = { ...process.env };
childEnvironment[NOTEBOOK_PROCESS_ENDPOINT_ENV] = endpointPath;
delete childEnvironment[NOTEBOOK_PROCESS_REGISTRY_ENV];

let child: ChildProcess | undefined;
let childExitCode = 1;
let finished = false;
let forceStopTimer: NodeJS.Timeout | undefined;
let portPollTimer: NodeJS.Timeout | undefined;
let shuttingDown = false;
let forcing = false;
let endpointWatcher: FSWatcher | undefined;
let endpointSettled = false;

const disposeEndpoint = () => {
  endpointSettled = true;
  endpointWatcher?.close();
  endpointWatcher = undefined;
  removeNotebookEndpointReceipt({ ownerNonce, processGroupId }, { directory });
};

const inspectEndpoint = () => {
  if (endpointSettled || shuttingDown || !child) return;
  let source;
  try {
    source = readFileSync(endpointPath, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return;
    failEndpoint(
      error instanceof Error ? error : new Error("Notebook endpoint failed", { cause: error }),
    );
    return;
  }
  try {
    const receipt = endpointSchema.parse(JSON.parse(source));
    if (
      receipt.pid === processGroupId ||
      ((process.platform === "darwin" || process.platform === "linux") &&
        processEnvironmentContains(receipt.pid, NOTEBOOK_PROCESS_OWNER_ENV, ownerNonce) !== true)
    ) {
      throw new Error("Notebook endpoint receipt does not identify its owned backend process");
    }
    process.kill(receipt.pid, 0);
    registerNotebookProcess({ ownerNonce, port: receipt.port, processGroupId }, { directory });
    port = receipt.port;
    disposeEndpoint();
    send({ type: "bound", port });
  } catch (error) {
    failEndpoint(
      error instanceof Error ? error : new Error("Notebook endpoint failed", { cause: error }),
    );
  }
};

const failEndpoint = (error: Error) => {
  disposeEndpoint();
  send({
    type: "failed",
    message: `Invalid notebook endpoint receipt: ${error.message}`,
  });
  beginShutdown(true);
};

const send = (message: SupervisorMessage) => {
  if (!process.connected || !process.send) return;
  try {
    process.send(message, () => undefined);
  } catch {
    beginShutdown(true);
  }
};

const finish = () => {
  if (finished) return;
  finished = true;
  clearTimeout(forceStopTimer);
  clearTimeout(portPollTimer);
  disposeEndpoint();
  unregisterNotebookProcess({ ownerNonce, processGroupId }, { directory });
  process.exitCode = childExitCode;
  if (process.connected) process.disconnect();
};

const finishWhenPortCloses = async (deadline = Date.now() + PORT_CLOSE_TIMEOUT) => {
  if (finished) return;
  if (await portIsOpen(port)) {
    if (Date.now() >= deadline) {
      forceStop();
      return;
    }
    portPollTimer = setTimeout(() => void finishWhenPortCloses(deadline), PORT_POLL_INTERVAL);
    return;
  }
  finish();
};

const forceStop = () => {
  forcing = true;
  if (process.platform === "win32") {
    stopProcessGroup(child?.pid, "SIGKILL");
    return;
  }
  const members = liveProcessGroupMembers(processGroupId);
  if (members === undefined) throw new Error("Cannot inspect notebook process group for shutdown");
  const backends = members.filter((pid) => pid !== processGroupId);
  if (backends.length === 0) {
    finish();
    return;
  }
  for (const pid of backends) {
    try {
      process.kill(pid, "SIGKILL");
    } catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error;
    }
  }
  if (child?.exitCode !== null || child?.signalCode !== null) void finishWhenPortCloses();
};

const beginShutdown = (signalGroup: boolean, force = true) => {
  if (shuttingDown || finished) return;
  shuttingDown = true;
  disposeEndpoint();
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
  try {
    registerNotebookProcess({ ownerNonce, port, processGroupId }, { directory });
  } catch (error) {
    failEndpoint(
      error instanceof Error ? error : new Error("Notebook endpoint failed", { cause: error }),
    );
    return;
  }
  try {
    endpointWatcher = watch(directory, (_event, filename) => {
      if (filename === null || filename.toString() === `${processGroupId}-${ownerNonce}.endpoint`) {
        inspectEndpoint();
      }
    });
    endpointWatcher.once("error", failEndpoint);
    child = spawn(command, args, {
      cwd: process.cwd(),
      env: childEnvironment,
      stdio: ["ignore", "inherit", "inherit"],
    });
  } catch (error) {
    failEndpoint(
      error instanceof Error ? error : new Error("Notebook endpoint failed", { cause: error }),
    );
    return;
  }
  child.once("error", (error) => {
    console.error(error);
    beginShutdown(false);
    finish();
  });
  child.once("spawn", () => {
    send({ type: "started" });
    inspectEndpoint();
  });
  child.once("exit", (code, signal) => {
    disposeEndpoint();
    const expected =
      (shuttingDown && (signal === "SIGTERM" || code === 143)) ||
      (forcing && (signal === "SIGKILL" || code === 137));
    childExitCode = expected ? 0 : (code ?? 1);
    if (!expected && (signal !== null || code !== 0)) {
      send({
        type: "failed",
        message: `Notebook service exited unexpectedly with ${signal ?? code}`,
      });
    }
    void finishWhenPortCloses();
  });
};

process.on("disconnect", () => beginShutdown(true));
process.on("SIGINT", () => beginShutdown(true, false));
process.on("SIGHUP", () => beginShutdown(true, false));
process.on("SIGTERM", () => beginShutdown(true, false));
process.on("message", (message) => {
  if (z.object({ type: z.literal("start") }).safeParse(message).success) start();
});

if (!process.connected || !process.send) {
  finish();
} else {
  send({ type: "registered" });
}
