import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { connect } from "node:net";

export type ProcessOwnerState = "foreign" | "owned" | "stopped" | "unknown";

export const liveProcessGroupMembers = (processGroupId: number): number[] | undefined => {
  const result = spawnSync("ps", ["-axo", "pid=,pgid=,stat="], {
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) return undefined;
  return result.stdout
    .split("\n")
    .map((line) => line.trim().split(/\s+/))
    .filter((fields) => fields.length >= 3)
    .map(([pid, group, state]) => ({
      group: Number(group),
      pid: Number(pid),
      state,
    }))
    .filter(
      ({ group, pid, state }) =>
        group === processGroupId && Number.isSafeInteger(pid) && pid > 0 && !state.startsWith("Z"),
    )
    .map(({ pid }) => pid)
    .sort((left, right) => left - right);
};

interface ProcessInspection {
  platform?: NodeJS.Platform;
  readFile?: (path: string) => Buffer;
  run?: (
    command: string,
    args: string[],
    options: { encoding: "utf8"; maxBuffer: number },
  ) => { error?: Error; status: number | null; stdout: string };
}

export const processEnvironmentContains = (
  pid: number,
  name: string,
  value: string,
  { platform = process.platform, readFile = readFileSync, run = spawnSync }: ProcessInspection = {},
): boolean | undefined => {
  const marker = `${name}=${value}`;
  if (platform === "linux") {
    try {
      return readFile(`/proc/${pid}/environ`).toString("utf8").split("\0").includes(marker);
    } catch {
      return undefined;
    }
  }
  if (platform !== "darwin") return undefined;
  const result = run("ps", ["eww", "-p", String(pid), "-o", "command="], {
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) return undefined;
  return result.stdout.split(/\s+/).includes(marker);
};

const sameMembers = (left: number[], right: number[]) =>
  left.length === right.length && left.every((pid, index) => pid === right[index]);

export const processGroupOwnerState = (
  processGroupId: number,
  environmentName: string,
  ownerNonce: string,
): ProcessOwnerState => {
  if (process.platform !== "darwin" && process.platform !== "linux") {
    return "unknown";
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const members = liveProcessGroupMembers(processGroupId);
    if (members === undefined) return "unknown";
    if (members.length === 0) return "stopped";
    const matches = members.map((pid) =>
      processEnvironmentContains(pid, environmentName, ownerNonce),
    );
    if (matches.every((match) => match === true)) return "owned";
    const refreshed = liveProcessGroupMembers(processGroupId);
    if (refreshed === undefined) return "unknown";
    if (sameMembers(members, refreshed)) {
      return matches.some((match) => match === false) ? "foreign" : "unknown";
    }
  }
  return "unknown";
};

export const stopProcessGroup = (
  processGroupId: number | undefined,
  signal: NodeJS.Signals = "SIGTERM",
): void => {
  if (processGroupId === undefined) return;
  const selected = signal === "SIGINT" ? "SIGTERM" : signal;
  if (process.platform === "win32") {
    spawnSync(
      "taskkill",
      ["/PID", String(processGroupId), "/T", ...(selected === "SIGKILL" ? ["/F"] : [])],
      {
        stdio: "ignore",
        windowsHide: true,
      },
    );
    return;
  }
  try {
    process.kill(-processGroupId, selected);
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) throw error;
  }
};

export const processGroupIsRunning = (processGroupId: number | undefined): boolean | undefined => {
  if (processGroupId === undefined) return false;
  if (process.platform === "win32") return undefined;
  try {
    process.kill(-processGroupId, 0);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ESRCH") return false;
    if (error instanceof Error && "code" in error && error.code === "EPERM") return true;
    throw error;
  }
};

export const portIsOpen = (port: number | null, connectSocket = connect): Promise<boolean> =>
  port === null
    ? Promise.resolve(false)
    : new Promise((resolveOpen) => {
        const socket = connectSocket({ host: "127.0.0.1", port });
        const finish = (open: boolean) => {
          clearTimeout(deadline);
          socket.destroy();
          resolveOpen(open);
        };
        const deadline = setTimeout(() => finish(true), 1_000);
        socket.once("connect", () => finish(true));
        socket.once("error", (error) =>
          finish(!("code" in error && error.code === "ECONNREFUSED")),
        );
      });
