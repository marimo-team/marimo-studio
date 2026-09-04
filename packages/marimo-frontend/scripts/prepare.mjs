import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { prepareMarimoSource } from "./source.mjs";

const scriptPath = fileURLToPath(import.meta.url);
const defaultLockDirectory = resolve(dirname(scriptPath), "../.cache/prepare.lock");
const LOCK_WAIT_MS = 10 * 60 * 1_000;
const OWNER_WRITE_GRACE_MS = 2_000;
const RETRY_MS = 50;
const errorSchema = z.object({ code: z.string().optional() });
const ownerSchema = z.object({
  pid: z.number().int().positive(),
  startedAt: z.number().finite(),
  token: z.string().min(1),
});

const delay = (milliseconds) =>
  new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

const errorCode = (error) => errorSchema.safeParse(error).data?.code;

const readOwner = async (lockDirectory) => {
  try {
    return ownerSchema.safeParse(
      JSON.parse(await readFile(resolve(lockDirectory, "owner.json"), "utf8")),
    ).data;
  } catch {
    return undefined;
  }
};

const processIsAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return errorCode(error) !== "ESRCH";
  }
};

const staleLock = async (lockDirectory) => {
  const details = await stat(lockDirectory);
  const owner = await readOwner(lockDirectory);
  const stale = owner
    ? !processIsAlive(owner.pid)
    : Date.now() - details.mtimeMs >= OWNER_WRITE_GRACE_MS;
  return { details, stale };
};

const reapStaleLock = async (lockDirectory, observed, retirementToken) => {
  let current;
  try {
    current = await stat(lockDirectory);
  } catch (error) {
    if (errorCode(error) === "ENOENT") {
      return true;
    }
    throw error;
  }
  if (current.dev !== observed.dev || current.ino !== observed.ino) {
    return false;
  }
  const retired = `${lockDirectory}.stale-${String(observed.dev)}-${String(observed.ino)}-${retirementToken()}`;
  try {
    await rename(lockDirectory, retired);
  } catch (error) {
    if (errorCode(error) === "ENOENT") {
      return true;
    }
    if (errorCode(error) === "EEXIST" || errorCode(error) === "ENOTEMPTY") {
      return false;
    }
    throw error;
  }
  await rm(retired, { force: true, recursive: true });
  return true;
};

const acquireLock = async (lockDirectory, waitMs, retirementToken) => {
  const owner = {
    pid: process.pid,
    startedAt: Date.now(),
    token: randomUUID(),
  };
  const deadline = Date.now() + waitMs;
  while (true) {
    try {
      await mkdir(lockDirectory);
      try {
        await writeFile(
          resolve(lockDirectory, "owner.json"),
          `${JSON.stringify(owner, null, 2)}\n`,
          "utf8",
        );
      } catch (error) {
        await rm(lockDirectory, { force: true, recursive: true });
        throw error;
      }
      return owner.token;
    } catch (error) {
      if (errorCode(error) !== "EEXIST") {
        throw error;
      }
    }

    const observed = await staleLock(lockDirectory).catch((error) => {
      if (errorCode(error) === "ENOENT") {
        return undefined;
      }
      throw error;
    });
    if (observed?.stale) {
      const reaped = await reapStaleLock(lockDirectory, observed.details, retirementToken);
      if (reaped) {
        continue;
      }
    }
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for Marimo source preparation lock ${lockDirectory}`);
    }
    await delay(RETRY_MS);
  }
};

const releaseLock = async (lockDirectory, token) => {
  const owner = await readOwner(lockDirectory);
  if (owner?.token === token) {
    await rm(lockDirectory, { force: true, recursive: true });
  }
};

export const withPreparationLock = async (
  action,
  {
    lockDirectory = defaultLockDirectory,
    retirementToken = randomUUID,
    waitMs = LOCK_WAIT_MS,
  } = {},
) => {
  await mkdir(dirname(lockDirectory), { recursive: true });
  const token = await acquireLock(lockDirectory, waitMs, retirementToken);
  try {
    return await action();
  } finally {
    await releaseLock(lockDirectory, token);
  }
};

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  await withPreparationLock(prepareMarimoSource);
}
