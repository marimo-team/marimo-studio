import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";

const PROCESS_OWNER_STATES = Object.freeze({
  foreign: "foreign",
  owned: "owned",
  stopped: "stopped",
  unknown: "unknown",
});

const liveProcessGroupMembers = (processGroupId) => {
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

export const processEnvironmentContains = (
  pid,
  name,
  value,
  { platform = process.platform, readFile = readFileSync, run = spawnSync } = {},
) => {
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

const sameMembers = (left, right) =>
  left.length === right.length && left.every((pid, index) => pid === right[index]);

export const processGroupOwnerState = (processGroupId, environmentName, ownerNonce) => {
  if (process.platform !== "darwin" && process.platform !== "linux") {
    return PROCESS_OWNER_STATES.unknown;
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const members = liveProcessGroupMembers(processGroupId);
    if (members === undefined) return PROCESS_OWNER_STATES.unknown;
    if (members.length === 0) return PROCESS_OWNER_STATES.stopped;
    const matches = members.map((pid) =>
      processEnvironmentContains(pid, environmentName, ownerNonce),
    );
    if (matches.every((match) => match === true)) return PROCESS_OWNER_STATES.owned;
    const refreshed = liveProcessGroupMembers(processGroupId);
    if (refreshed === undefined) return PROCESS_OWNER_STATES.unknown;
    if (sameMembers(members, refreshed)) {
      return matches.some((match) => match === false)
        ? PROCESS_OWNER_STATES.foreign
        : PROCESS_OWNER_STATES.unknown;
    }
  }
  return PROCESS_OWNER_STATES.unknown;
};

export const stopProcessGroup = (processGroupId, signal = "SIGTERM") => {
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
    if (error?.code !== "ESRCH") throw error;
  }
};

export const processGroupIsRunning = (processGroupId) => {
  if (process.platform === "win32") return undefined;
  try {
    process.kill(-processGroupId, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") return false;
    if (error?.code === "EPERM") return true;
    throw error;
  }
};
