import type { Stats } from "node:fs";

import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { z } from "zod";

import { prepareMarimoSource } from "./source.ts";

const lockDirectory = join(import.meta.dirname, "..", ".cache", "prepare.lock");
const ownerPath = join(lockDirectory, "owner.json");
const LOCK_WAIT_MS = 10 * 60 * 1_000;
const OWNER_WRITE_GRACE_MS = 2_000;
const RETRY_MS = 50;
const errorSchema = z.object({ code: z.string().optional() });
const ownerSchema = z.object({
  pid: z.number().int().positive(),
  startedAt: z.number().finite(),
  token: z.string().min(1),
});

const errorCode = (cause: unknown): string | undefined => errorSchema.safeParse(cause).data?.code;

const readOwner = async () => {
  try {
    return ownerSchema.safeParse(JSON.parse(await readFile(ownerPath, "utf8"))).data;
  } catch {
    return undefined;
  }
};

const processIsAlive = (pid: number): boolean => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return errorCode(error) !== "ESRCH";
  }
};

const staleLock = async () => {
  const details = await stat(lockDirectory);
  const owner = await readOwner();
  const stale = owner
    ? !processIsAlive(owner.pid)
    : Date.now() - details.mtimeMs >= OWNER_WRITE_GRACE_MS;
  return { details, stale };
};

const reapStaleLock = async (observed: Stats): Promise<boolean> => {
  let current: Stats;
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
  const retired = `${lockDirectory}.stale-${String(observed.dev)}-${String(observed.ino)}-${randomUUID()}`;
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

const acquireLock = async (): Promise<string> => {
  const owner = {
    pid: process.pid,
    startedAt: Date.now(),
    token: randomUUID(),
  };
  const deadline = Date.now() + LOCK_WAIT_MS;
  while (true) {
    try {
      await mkdir(lockDirectory);
      try {
        await writeFile(ownerPath, `${JSON.stringify(owner, null, 2)}\n`, "utf8");
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

    const observed = await staleLock().catch((error) => {
      if (errorCode(error) === "ENOENT") {
        return undefined;
      }
      throw error;
    });
    if (observed?.stale && (await reapStaleLock(observed.details))) {
      continue;
    }
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for Marimo source preparation lock ${lockDirectory}`);
    }
    await delay(RETRY_MS);
  }
};

const releaseLock = async (token: string) => {
  const owner = await readOwner();
  if (owner?.token === token) {
    await rm(lockDirectory, { force: true, recursive: true });
  }
};

await mkdir(dirname(lockDirectory), { recursive: true });
const token = await acquireLock();
try {
  await prepareMarimoSource();
} finally {
  await releaseLock(token);
}
