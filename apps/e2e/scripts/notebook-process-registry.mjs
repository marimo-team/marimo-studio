import { randomBytes } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  rmdirSync,
  writeFileSync,
} from "node:fs";
import { connect } from "node:net";
import { resolve } from "node:path";
import { z } from "zod";

import { notebookProcessRegistryDirectory } from "./paths.mjs";
import { processGroupOwnerState, stopProcessGroup } from "./process-group.mjs";

export const NOTEBOOK_PROCESS_OWNER_ENV = "MARIMO_STUDIO_E2E_PROCESS_OWNER";
export const NOTEBOOK_PROCESS_PORT_ENV = "MARIMO_STUDIO_E2E_PROCESS_PORT";
export const NOTEBOOK_PROCESS_REGISTRY_ENV = "MARIMO_STUDIO_E2E_PROCESS_REGISTRY";

const DEFAULT_STOP_TIMEOUT = 5_000;
const STOP_POLL_INTERVAL = 50;
const REGISTRY_CLOSING_FILE = ".closing";
const recordSchema = z.object({
  ownerNonce: z.string().regex(/^[a-f\d]{64}$/),
  port: z.number().int().positive().max(65_535),
  processGroupId: z.number().int().positive().safe(),
});

export const createNotebookProcessOwnerNonce = () => randomBytes(32).toString("hex");

const recordPath = (directory, processGroupId, ownerNonce) =>
  resolve(directory, `${processGroupId}-${ownerNonce}.json`);

const closingPath = (directory) => resolve(directory, REGISTRY_CLOSING_FILE);

export const closeNotebookProcessRegistry = ({
  directory = notebookProcessRegistryDirectory,
} = {}) => {
  mkdirSync(directory, { recursive: true });
  try {
    writeFileSync(closingPath(directory), String(process.pid), {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
  }
};

const parseRecord = (source, path) => {
  let record;
  try {
    record = recordSchema.parse(JSON.parse(source));
  } catch {
    throw new Error(`Invalid E2E notebook process record: ${path}`);
  }
  return Object.freeze({
    ownerNonce: record.ownerNonce,
    path,
    port: record.port,
    processGroupId: record.processGroupId,
  });
};

const readRecords = (directory) => {
  let names;
  try {
    names = readdirSync(directory);
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
  const records = [];
  for (const name of names.filter((candidate) => candidate.endsWith(".json"))) {
    const path = resolve(directory, name);
    try {
      records.push(parseRecord(readFileSync(path, "utf8"), path));
    } catch {
      // Records without a verifiable owner can never authorize a signal.
      rmSync(path, { force: true });
    }
  }
  return records;
};

const removeDirectoryIfEmpty = (directory) => {
  try {
    rmdirSync(directory);
  } catch (error) {
    if (error?.code !== "ENOENT" && error?.code !== "ENOTEMPTY") throw error;
  }
};

const portIsOpen = (port) =>
  new Promise((resolveOpen) => {
    const socket = connect({ host: "127.0.0.1", port });
    const finish = (open) => {
      socket.destroy();
      resolveOpen(open);
    };
    socket.setTimeout(100, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });

const ownerState = (record) =>
  processGroupOwnerState(record.processGroupId, NOTEBOOK_PROCESS_OWNER_ENV, record.ownerNonce);

const removeRecord = (record, directory) => {
  rmSync(record.path, { force: true });
  removeDirectoryIfEmpty(directory);
};

const signalOwned = async (records, signal, inspect, isPortOpen, stop, directory) => {
  const signaled = [];
  const blocked = [];
  for (const record of records) {
    const state = inspect(record);
    if (state !== "owned") {
      if (await isPortOpen(record.port)) {
        blocked.push({ record, state });
        continue;
      }
      removeRecord(record, directory);
      continue;
    }
    stop(record.processGroupId, signal);
    signaled.push(record);
  }
  return { blocked, signaled };
};

const pendingRecords = async (records, inspect, isPortOpen, directory) => {
  const blocked = [];
  const pending = [];
  for (const record of records) {
    const state = inspect(record);
    if (state === "foreign" || state === "unknown") {
      if (await isPortOpen(record.port)) {
        blocked.push({ record, state });
        continue;
      }
      removeRecord(record, directory);
      continue;
    }
    if (state === "owned" || (await isPortOpen(record.port))) {
      pending.push({ record, state });
      continue;
    }
    removeRecord(record, directory);
  }
  return { blocked, pending };
};

const waitForStopped = async (records, inspect, isPortOpen, directory, timeout) => {
  const deadline = Date.now() + timeout;
  const blocked = [];
  let result = await pendingRecords(records, inspect, isPortOpen, directory);
  blocked.push(...result.blocked);
  let { pending } = result;
  while (pending.length > 0 && Date.now() < deadline) {
    await new Promise((resolveWait) => setTimeout(resolveWait, STOP_POLL_INTERVAL));
    result = await pendingRecords(
      pending.map(({ record }) => record),
      inspect,
      isPortOpen,
      directory,
    );
    blocked.push(...result.blocked);
    pending = result.pending;
  }
  return { blocked, pending };
};

export const registerNotebookProcess = (
  { ownerNonce, port, processGroupId },
  { directory = notebookProcessRegistryDirectory } = {},
) => {
  if (existsSync(closingPath(directory))) {
    throw new Error("E2E notebook process registry is closing");
  }
  const record = parseRecord(JSON.stringify({ ownerNonce, port, processGroupId }), "new record");
  mkdirSync(directory, { recursive: true });
  const path = recordPath(directory, record.processGroupId, record.ownerNonce);
  const temporaryPath = `${path}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, JSON.stringify({ ownerNonce, port, processGroupId }), {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  try {
    renameSync(temporaryPath, path);
  } finally {
    rmSync(temporaryPath, { force: true });
  }
  if (existsSync(closingPath(directory))) {
    rmSync(path, { force: true });
    throw new Error("E2E notebook process registry closed during registration");
  }
};

export const unregisterNotebookProcess = (
  { ownerNonce, processGroupId },
  { directory = notebookProcessRegistryDirectory } = {},
) => {
  rmSync(recordPath(directory, processGroupId, ownerNonce), { force: true });
  removeDirectoryIfEmpty(directory);
};

export const stopRegisteredNotebookProcesses = async ({
  directory = notebookProcessRegistryDirectory,
  inspect = ownerState,
  isPortOpen = portIsOpen,
  signal = "SIGTERM",
  stop = stopProcessGroup,
  timeout = DEFAULT_STOP_TIMEOUT,
} = {}) => {
  const records = readRecords(directory);
  removeDirectoryIfEmpty(directory);
  const initial = await signalOwned(records, signal, inspect, isPortOpen, stop, directory);
  let result = await waitForStopped(initial.signaled, inspect, isPortOpen, directory, timeout);
  const blocked = [...initial.blocked, ...result.blocked];
  let { pending } = result;
  if (pending.length > 0 && signal !== "SIGKILL") {
    const forced = await signalOwned(
      pending.filter(({ state }) => state === "owned").map(({ record }) => record),
      "SIGKILL",
      inspect,
      isPortOpen,
      stop,
      directory,
    );
    blocked.push(...forced.blocked);
    const stoppedGroups = pending
      .filter(({ state }) => state === "stopped")
      .map(({ record }) => record);
    result = await waitForStopped(
      [...forced.signaled, ...stoppedGroups],
      inspect,
      isPortOpen,
      directory,
      timeout,
    );
    blocked.push(...result.blocked);
    pending = result.pending;
  }
  const survived = [...blocked, ...pending];
  if (survived.length > 0) {
    throw new Error(
      `E2E notebook processes survived shutdown: ${survived
        .map(({ record, state }) =>
          state === "owned"
            ? `${record.processGroupId} on port ${record.port}`
            : `${state} owner at ${record.path} on live port ${record.port}`,
        )
        .join(", ")}`,
    );
  }
};
