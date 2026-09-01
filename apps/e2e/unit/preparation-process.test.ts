import type { ChildProcess, SpawnOptions } from "node:child_process";

import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { expect, test } from "vite-plus/test";
import { z } from "zod";

import { PreparationCancelled, PreparationProcessOwner } from "../scripts/preparation-process.mjs";
import { stopProcessGroup } from "../scripts/process-group.mjs";

const boundAddressSchema = z.object({ port: z.number().int().positive() });
const PROBE_TIMEOUT = 500;
const PROCESS_START_TIMEOUT = 5_000;

const availablePort = async (): Promise<number> => {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = boundAddressSchema.parse(server.address());
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error === undefined ? resolve() : reject(error)));
  });
  return address.port;
};

const responds = async (port: number): Promise<boolean> => {
  try {
    const response = await fetch(`http://127.0.0.1:${port}`, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT),
    });
    await response.body?.cancel();
    return response.ok;
  } catch {
    return false;
  }
};

test("stops a preparation descendant after its wrapper exits", async () => {
  const port = await availablePort();
  const descendant = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((_request, response) => response.end("ready"))
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const wrapper = `
    const { spawn } = require("node:child_process");
    spawn(process.execPath, ["-e", ${JSON.stringify(descendant)}], { stdio: "ignore" });
    process.on("SIGTERM", () => process.exit(0));
    setInterval(() => {}, 1_000);
  `;
  let leader: ChildProcess | undefined;
  const owner = new PreparationProcessOwner({
    spawn: (command: string, args: string[], options: SpawnOptions) => {
      leader = spawn(command, args, options);
      return leader;
    },
  });
  const running = owner.run("test preparation", process.execPath, ["-e", wrapper], {
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    stdio: "ignore",
  });

  try {
    await expect.poll(() => responds(port), { timeout: PROCESS_START_TIMEOUT }).toBe(true);
    const stopped = owner.stop("SIGTERM", 200);
    await expect(running).rejects.toBeInstanceOf(PreparationCancelled);
    await expect(stopped).resolves.toBeUndefined();
    expect(await responds(port)).toBe(false);
  } finally {
    if (leader?.pid !== undefined) {
      stopProcessGroup(leader.pid, "SIGKILL");
    }
  }
}, 10_000);

test("does not spawn another preparation phase after cancellation", async () => {
  let spawns = 0;
  const owner = new PreparationProcessOwner({
    spawn: () => {
      spawns += 1;
      throw new Error("spawned after cancellation");
    },
  });

  await owner.stop("SIGTERM", 100);

  await expect(
    owner.run("late preparation", process.execPath, ["-e", "process.exit(0)"]),
  ).rejects.toBeInstanceOf(PreparationCancelled);
  expect(spawns).toBe(0);
});
