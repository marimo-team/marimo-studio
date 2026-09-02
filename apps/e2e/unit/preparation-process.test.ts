import type { ChildProcess, SpawnOptions } from "node:child_process";

import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { createServer } from "node:net";
import { expect, test } from "vite-plus/test";
import { z } from "zod";

import { PreparationCancelled, PreparationProcessOwner } from "../scripts/preparation-process.mjs";
import { stopProcessGroup } from "../scripts/process-group.mjs";

const boundAddressSchema = z.object({ port: z.number().int().positive() });
const capturedFailureSchema = z.object({ message: z.string(), stdout: z.string() });
const commandFailureSchema = capturedFailureSchema.extend({ code: z.number(), stderr: z.string() });
const PROBE_TIMEOUT = 500;
const PROCESS_START_TIMEOUT = 5_000;
const posixTest = process.platform === "win32" ? test.skip : test;

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

const startVictimProcessGroup = async () => {
  const port = await availablePort();
  const victim = spawn(
    process.execPath,
    [
      "-e",
      `require("node:http").createServer((_request, response) => response.end("ready")).listen(${port}, "127.0.0.1")`,
    ],
    { detached: true, stdio: "ignore" },
  );
  await expect.poll(() => responds(port), { timeout: PROCESS_START_TIMEOUT }).toBe(true);
  return { port, process: victim };
};

const reusedProcessGroupChild = (pid: number | undefined): ChildProcess => {
  // SAFETY: The owner reads `pid` and subscribes to process events on this synthetic child.
  const child = new EventEmitter() as ChildProcess;
  Object.assign(child, { pid });
  return child;
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
    const stopped = owner.stopLeaders("SIGTERM", 1_000, 200);
    await expect(running).rejects.toBeInstanceOf(PreparationCancelled);
    await expect(stopped).resolves.toBeUndefined();
    expect(await responds(port)).toBe(false);
  } finally {
    if (leader?.pid !== undefined) {
      stopProcessGroup(leader.pid, "SIGKILL");
    }
  }
}, 10_000);

posixTest(
  "lets a preparation leader close its detached descendant",
  async () => {
    const port = await availablePort();
    const descendant = `
    const { createServer } = require("node:http");
    createServer((_request, response) => response.end("ready"))
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
    const wrapper = `
    const { spawn } = require("node:child_process");
    const child = spawn(process.execPath, ["-e", ${JSON.stringify(descendant)}], {
      detached: true,
      env: process.env,
      stdio: "ignore",
    });
    let stopping = false;
    process.on("SIGTERM", () => {
      if (stopping) return;
      stopping = true;
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch (error) {
        if (error.code !== "ESRCH") throw error;
      }
      child.once("close", () => process.exit(0));
    });
    setInterval(() => {}, 1_000);
  `;
    const owner = new PreparationProcessOwner();
    const running = owner.run("leader-owned cleanup", process.execPath, ["-e", wrapper], {
      env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
      stdio: "ignore",
    });

    try {
      await expect.poll(() => responds(port), { timeout: PROCESS_START_TIMEOUT }).toBe(true);
      const stopped = owner.stopLeaders("SIGTERM", 2_000, 200);
      await expect(running).rejects.toBeInstanceOf(PreparationCancelled);
      await expect(stopped).resolves.toBeUndefined();
      expect(await responds(port)).toBe(false);
    } finally {
      await owner.stop("SIGKILL");
    }
  },
  10_000,
);

posixTest(
  "does not signal a process group after its identifier is reused",
  async () => {
    const victim = await startVictimProcessGroup();
    const reused = reusedProcessGroupChild(victim.process.pid);
    const owner = new PreparationProcessOwner({ spawn: () => reused });

    try {
      const completed = owner.run("completed preparation", process.execPath, []);
      reused.emit("exit", 0, null);

      await expect(completed).resolves.toBeUndefined();
      expect(await responds(victim.port)).toBe(true);
    } finally {
      if (victim.process.pid !== undefined) {
        stopProcessGroup(victim.process.pid, "SIGKILL");
      }
    }
  },
  10_000,
);

posixTest(
  "does not signal a reused process group before the exit callback",
  async () => {
    const victim = await startVictimProcessGroup();
    const reused = reusedProcessGroupChild(victim.process.pid);
    const owner = new PreparationProcessOwner({ spawn: () => reused });

    try {
      const running = owner.run("exited preparation", process.execPath, []);
      await expect(owner.stop("SIGTERM", 200)).resolves.toBeUndefined();
      expect(await responds(victim.port)).toBe(true);

      reused.emit("exit", 0, null);
      await expect(running).rejects.toBeInstanceOf(PreparationCancelled);
    } finally {
      if (victim.process.pid !== undefined) {
        stopProcessGroup(victim.process.pid, "SIGKILL");
      }
    }
  },
  10_000,
);

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

test("captures command output through the owned process boundary", async () => {
  const owner = new PreparationProcessOwner();
  try {
    const output = await owner.runCaptured(
      "captured command",
      process.execPath,
      ["-e", 'process.stdout.write("ready"); process.stderr.write("warning")'],
      {},
      { timeout: 1_000 },
    );

    expect(output).toEqual({ stderr: "warning", stdout: "ready" });
  } finally {
    await owner.stop("SIGKILL");
  }
});

test("preserves captured output when the command fails", async () => {
  const owner = new PreparationProcessOwner();
  try {
    const failure = await owner
      .runCaptured(
        "failed command",
        process.execPath,
        [
          "-e",
          'process.stdout.write("partial output"); process.stderr.write("invalid input"); process.exit(2)',
        ],
        {},
        { timeout: 1_000 },
      )
      .then(
        () => undefined,
        (error) => commandFailureSchema.parse(error),
      );

    expect(failure).toMatchObject({
      code: 2,
      stderr: "invalid input",
      stdout: "partial output",
    });
    expect(failure?.message).toContain("invalid input");
  } finally {
    await owner.stop("SIGKILL");
  }
});

test("a timed-out command stops its signal-resistant descendant", async () => {
  const port = await availablePort();
  const descendant = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((_request, response) => response.end("ready"))
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1", () => {
        console.log("descendant-ready");
      });
  `;
  const wrapper = `
    const { spawn } = require("node:child_process");
    spawn(process.execPath, ["-e", ${JSON.stringify(descendant)}], { stdio: "inherit" });
    setInterval(() => {}, 1_000);
  `;
  const owner = new PreparationProcessOwner();
  let failure: z.infer<typeof capturedFailureSchema> | undefined;
  try {
    await owner
      .runCaptured(
        "timed command",
        process.execPath,
        ["-e", wrapper],
        { env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) } },
        { timeout: 1_000 },
      )
      .catch((error) => {
        failure = capturedFailureSchema.parse(error);
      });

    expect(failure).toMatchObject({ stdout: expect.stringContaining("descendant-ready") });
    expect(failure?.message).toContain("timed command exceeded 1000ms");
    expect(await responds(port)).toBe(false);
  } finally {
    await owner.stop("SIGKILL");
  }
}, 20_000);

test("preserves cancellation when concurrent process cleanup fails", async () => {
  // SAFETY: The owner reads only `pid` and subscribes with `once` in this synthetic failure case.
  const child = new EventEmitter() as ChildProcess;
  Object.assign(child, { pid: undefined });
  const owner = new PreparationProcessOwner({ spawn: () => child });
  const running = owner.run("test preparation", process.execPath, []);

  const stopping = owner.stop("SIGTERM", 0);
  await expect(stopping).rejects.toThrow("survived shutdown");
  const cancelled = expect(running).rejects.toBeInstanceOf(PreparationCancelled);
  child.emit("exit", null, "SIGTERM");
  await cancelled;
});
