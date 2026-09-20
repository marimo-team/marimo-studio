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
import { resolve } from "node:path";
import { z } from "zod";

import { notebookProcessRegistryDirectory } from "./paths.ts";
import {
  portIsOpen,
  processGroupOwnerState,
  stopProcessGroup,
  type ProcessOwnerState,
} from "./process-group.ts";

export const NOTEBOOK_PROCESS_OWNER_ENV = "MARIMO_STUDIO_E2E_PROCESS_OWNER";
export const NOTEBOOK_PROCESS_ENDPOINT_ENV = "MARIMO_STUDIO_E2E_ENDPOINT_FILE";
export const NOTEBOOK_PROCESS_PORT_ENV = "MARIMO_STUDIO_E2E_PROCESS_PORT";
export const NOTEBOOK_PROCESS_REGISTRY_ENV = "MARIMO_STUDIO_E2E_PROCESS_REGISTRY";

const DEFAULT_STOP_TIMEOUT = 5_000;
const STOP_POLL_INTERVAL = 50;
const REGISTRY_CLOSING_FILE = ".closing";
const recordSchema = z.object({
  ownerNonce: z.string().regex(/^[a-f\d]{64}$/),
  port: z.number().int().positive().max(65_535).nullable(),
  processGroupId: z.number().int().positive().safe(),
});

export interface NotebookProcessOwner {
  ownerNonce: string;
  processGroupId: number;
}
interface NotebookProcessRecord extends NotebookProcessOwner {
  port: number | null;
  path: string;
}
type InspectOwner = (record: NotebookProcessRecord) => ProcessOwnerState;
type PortProbe = (port: number | null) => Promise<boolean>;
interface RegistryOptions {
  directory?: string;
}

export const createNotebookProcessOwnerNonce = () => randomBytes(32).toString("hex");

const recordPath = (directory: string, processGroupId: number, ownerNonce: string) =>
  resolve(directory, `${processGroupId}-${ownerNonce}.json`);

export const notebookProcessEndpointPath = (
  directory: string,
  processGroupId: number,
  ownerNonce: string,
) => resolve(directory, `${processGroupId}-${ownerNonce}.endpoint`);

export const removeNotebookEndpointReceipt = (
  { ownerNonce, processGroupId }: NotebookProcessOwner,
  { directory }: { directory: string },
) => {
  const filename = `${processGroupId}-${ownerNonce}.endpoint`;
  let names;
  try {
    names = readdirSync(directory);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return;
    throw error;
  }
  for (const name of names) {
    if (name === filename || (name.startsWith(`${filename}.`) && name.endsWith(".tmp"))) {
      rmSync(resolve(directory, name), { force: true });
    }
  }
};

const closingPath = (directory: string) => resolve(directory, REGISTRY_CLOSING_FILE);

export const closeNotebookProcessRegistry = ({
  directory = notebookProcessRegistryDirectory,
}: RegistryOptions = {}) => {
  mkdirSync(directory, { recursive: true });
  try {
    writeFileSync(closingPath(directory), String(process.pid), {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;
  }
};

const parseRecord = (source: string, path: string) => {
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

const readRecords = (directory: string) => {
  let names;
  try {
    names = readdirSync(directory);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return [];
    throw error;
  }
  const records: NotebookProcessRecord[] = [];
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

const removeDirectoryIfEmpty = (directory: string) => {
  try {
    rmdirSync(directory);
  } catch (error) {
    if (
      !(
        error instanceof Error &&
        "code" in error &&
        (error.code === "ENOENT" || error.code === "ENOTEMPTY")
      )
    )
      throw error;
  }
};

const ownerState = (record: NotebookProcessRecord) =>
  processGroupOwnerState(record.processGroupId, NOTEBOOK_PROCESS_OWNER_ENV, record.ownerNonce);

const removeRecord = (record: NotebookProcessRecord, directory: string) => {
  rmSync(record.path, { force: true });
  removeNotebookEndpointReceipt(record, { directory });
  removeDirectoryIfEmpty(directory);
};

const signalOwned = async (
  records: NotebookProcessRecord[],
  signal: NodeJS.Signals,
  inspect: InspectOwner,
  isPortOpen: PortProbe,
  stop: typeof stopProcessGroup,
  directory: string,
) => {
  const signaled = [];
  const blocked = [];
  for (const record of records) {
    const state = inspect(record);
    if (state !== "owned") {
      if (
        (record.port === null && state !== "stopped") ||
        (record.port !== null && (await isPortOpen(record.port)))
      ) {
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

const pendingRecords = async (
  records: NotebookProcessRecord[],
  inspect: InspectOwner,
  isPortOpen: PortProbe,
  directory: string,
) => {
  const blocked = [];
  const pending = [];
  for (const record of records) {
    const state = inspect(record);
    if (state === "foreign" || state === "unknown") {
      if (record.port === null || (record.port !== null && (await isPortOpen(record.port)))) {
        blocked.push({ record, state });
        continue;
      }
      removeRecord(record, directory);
      continue;
    }
    if (state === "owned" || (record.port !== null && (await isPortOpen(record.port)))) {
      pending.push({ record, state });
      continue;
    }
    removeRecord(record, directory);
  }
  return { blocked, pending };
};

const waitForStopped = async (
  records: NotebookProcessRecord[],
  inspect: InspectOwner,
  isPortOpen: PortProbe,
  directory: string,
  timeout: number,
) => {
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
  { ownerNonce, port, processGroupId }: NotebookProcessOwner & { port: number | null },
  { directory = notebookProcessRegistryDirectory }: RegistryOptions = {},
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
  { ownerNonce, processGroupId }: NotebookProcessOwner,
  { directory = notebookProcessRegistryDirectory }: RegistryOptions = {},
) => {
  rmSync(recordPath(directory, processGroupId, ownerNonce), { force: true });
  removeNotebookEndpointReceipt({ ownerNonce, processGroupId }, { directory });
  removeDirectoryIfEmpty(directory);
};

export const stopRegisteredNotebookProcesses = async ({
  directory = notebookProcessRegistryDirectory,
  inspect = ownerState,
  isPortOpen = portIsOpen,
  signal = "SIGTERM",
  stop = stopProcessGroup,
  timeout = DEFAULT_STOP_TIMEOUT,
}: RegistryOptions & {
  inspect?: InspectOwner;
  isPortOpen?: PortProbe;
  signal?: NodeJS.Signals;
  stop?: typeof stopProcessGroup;
  timeout?: number;
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
            ? `${record.processGroupId} ${record.port === null ? "awaiting backend binding" : `on port ${record.port}`}`
            : `${state} owner at ${record.path} ${record.port === null ? "awaiting backend binding" : `on live port ${record.port}`}`,
        )
        .join(", ")}`,
    );
  }
};
