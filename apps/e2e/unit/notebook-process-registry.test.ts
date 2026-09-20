import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, test, vi } from "vite-plus/test";
import { z } from "zod";

import {
  closeNotebookProcessRegistry,
  createNotebookProcessOwnerNonce,
  registerNotebookProcess,
  stopRegisteredNotebookProcesses,
  unregisterNotebookProcess,
} from "../scripts/notebook-process-registry.ts";
import { appDirectory } from "../scripts/paths.ts";
import { processGroupIsRunning, stopProcessGroup } from "../scripts/process-group.ts";
import {
  spawnRegisteredNotebookSupervisor,
  startRegisteredNotebookProcess,
} from "../scripts/registered-notebook-process.ts";

const boundAddressSchema = z.object({ port: z.number().int().positive() });
const supervisorMessageSchema = z.object({ processGroupId: z.number().int().positive() });
const registrationResultSchema = z.object({ registered: z.boolean() });
const supportsProcessEnvironmentInspection =
  process.platform === "darwin" || process.platform === "linux";
const launcherUrl = pathToFileURL(
  resolve(appDirectory, "scripts/registered-notebook-process.ts"),
).href;
const registryUrl = pathToFileURL(
  resolve(appDirectory, "scripts/notebook-process-registry.ts"),
).href;

const availablePort = async (): Promise<number> => {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = boundAddressSchema.parse(server.address());
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error === undefined ? resolveClose() : reject(error)));
  });
  return address.port;
};

const responds = async (port: number): Promise<boolean> => {
  try {
    const response = await fetch(`http://127.0.0.1:${port}`);
    await response.body?.cancel();
    return response.ok;
  } catch {
    return false;
  }
};

const signalResistantServer = `
  const { createServer } = require("node:http");
  process.on("SIGTERM", () => {});
  createServer((_request, response) => response.end("ready"))
    .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1", function () {
      const target = process.env.MARIMO_STUDIO_E2E_ENDPOINT_FILE;
      if (!target) return;
      const { writeFileSync, renameSync } = require("node:fs");
      writeFileSync(target + ".tmp", JSON.stringify({
        ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER,
        pid: process.pid, port: this.address().port,
      }));
      renameSync(target + ".tmp", target);
    });
`;

const waitForSupervisor = (worker: ChildProcess) =>
  new Promise<number>((resolveGroup, reject) => {
    worker.once("error", reject);
    worker.once("message", (message) =>
      resolveGroup(supervisorMessageSchema.parse(message).processGroupId),
    );
  });

const waitForExit = (child: ChildProcess) =>
  child.exitCode !== null || child.signalCode !== null
    ? Promise.resolve()
    : new Promise<void>((resolveClose) => child.once("exit", () => resolveClose()));

const workerSource = (directory: string, port: number, start: boolean) => `
  const launcher = await import(${JSON.stringify(launcherUrl)});
  const registration = launcher.${start ? "startRegisteredNotebookProcess" : "spawnRegisteredNotebookSupervisor"}({
    args: ["-e", ${JSON.stringify(signalResistantServer)}],
    command: process.execPath,
    cwd: process.cwd(),
    directory: ${JSON.stringify(directory)},
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: ${JSON.stringify(String(port))} },
    stdio: ["ignore", "ignore", "ignore"],
  });
  await registration.${start ? "ready" : "registered"};
  process.send({ processGroupId: registration.processGroupId });
  setInterval(() => {}, 1_000);
`;

test.skipIf(!supportsProcessEnvironmentInspection)(
  "runner shutdown owns a detached signal-resistant notebook process",
  async () => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
    const port = await availablePort();
    const registration = startRegisteredNotebookProcess({
      args: ["-e", signalResistantServer],
      command: process.execPath,
      cwd: process.cwd(),
      directory,
      env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
      stdio: ["ignore", "ignore", "ignore"],
    });
    try {
      await registration.ready;
      await expect.poll(() => responds(port)).toBe(true);

      await stopRegisteredNotebookProcesses({ directory, timeout: 100 });

      await expect.poll(() => responds(port)).toBe(false);
      expect(processGroupIsRunning(registration.processGroupId)).toBe(false);
      expect(existsSync(directory)).toBe(false);
    } finally {
      stopProcessGroup(registration.processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  10_000,
);

test("a delayed start gets a fresh readiness timeout", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
  const readyTimeout = 2_000;
  const registration = spawnRegisteredNotebookSupervisor({
    args: ["-e", "process.exit(0)"],
    command: process.execPath,
    cwd: process.cwd(),
    directory,
    env: process.env,
    readyTimeout,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.registered;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, readyTimeout + 100));

    await expect(registration.start()).resolves.toBeUndefined();
    await waitForExit(registration.child);
  } finally {
    registration.child.kill("SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
}, 10_000);

test("a supervisor spawn failure retains the operating system error", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
  const missingDirectory = resolve(directory, "missing");
  try {
    const registration = spawnRegisteredNotebookSupervisor({
      args: ["-e", "process.exit(0)"],
      command: process.execPath,
      cwd: missingDirectory,
      directory,
      env: process.env,
      readyTimeout: 1_000,
      stdio: ["ignore", "ignore", "ignore"],
    });

    await expect(registration.registered).rejects.toMatchObject({
      code: "ENOENT",
    });
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});

test.skipIf(!supportsProcessEnvironmentInspection)(
  "a stale record reports a live foreign process group without signaling it",
  async () => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
    const port = await availablePort();
    const child = spawn(process.execPath, ["-e", signalResistantServer], {
      detached: true,
      env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
      stdio: "ignore",
    });
    const processGroupId = child.pid;
    if (processGroupId === undefined) throw new Error("Detached foreign server has no process ID");
    try {
      await expect.poll(() => responds(port)).toBe(true);
      registerNotebookProcess(
        { ownerNonce: createNotebookProcessOwnerNonce(), port, processGroupId },
        { directory },
      );

      await expect(stopRegisteredNotebookProcesses({ directory, timeout: 100 })).rejects.toThrow(
        /foreign owner.*live port/,
      );

      expect(await responds(port)).toBe(true);
      expect(processGroupIsRunning(processGroupId)).toBe(true);
      expect(existsSync(directory)).toBe(true);

      const closed = waitForExit(child);
      stopProcessGroup(processGroupId, "SIGKILL");
      await closed;
      await expect.poll(() => responds(port)).toBe(false);
      await stopRegisteredNotebookProcesses({ directory, timeout: 100 });
      expect(existsSync(directory)).toBe(false);
    } finally {
      stopProcessGroup(processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  10_000,
);

test.skipIf(!supportsProcessEnvironmentInspection)(
  "worker termination before start launches no notebook process",
  async () => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
    const port = await availablePort();
    let processGroupId: number | undefined;
    let worker: ChildProcess | undefined;
    try {
      worker = spawn(
        process.execPath,
        ["--input-type=module", "-e", workerSource(directory, port, false)],
        {
          cwd: appDirectory,
          stdio: ["ignore", "ignore", "ignore", "ipc"],
        },
      );
      processGroupId = await waitForSupervisor(worker);
      worker.kill("SIGKILL");
      await waitForExit(worker);

      expect(await responds(port)).toBe(false);
      await expect.poll(() => processGroupIsRunning(processGroupId)).toBe(false);
      expect(existsSync(directory)).toBe(false);
    } finally {
      if (worker?.exitCode === null && worker.signalCode === null) worker.kill("SIGKILL");
      if (processGroupId !== undefined) stopProcessGroup(processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  15_000,
);

test.skipIf(!supportsProcessEnvironmentInspection)(
  "worker termination after start stops its signal-resistant notebook group",
  async () => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
    const port = await availablePort();
    let processGroupId: number | undefined;
    let worker: ChildProcess | undefined;
    try {
      worker = spawn(
        process.execPath,
        ["--input-type=module", "-e", workerSource(directory, port, true)],
        {
          cwd: appDirectory,
          stdio: ["ignore", "ignore", "ignore", "ipc"],
        },
      );
      processGroupId = await waitForSupervisor(worker);
      await expect.poll(() => responds(port)).toBe(true);
      worker.kill("SIGKILL");
      await waitForExit(worker);

      await expect.poll(() => responds(port), { timeout: 10_000 }).toBe(false);
      await expect.poll(() => processGroupIsRunning(processGroupId)).toBe(false);
      expect(existsSync(directory)).toBe(false);
    } finally {
      if (worker?.exitCode === null && worker.signalCode === null) worker.kill("SIGKILL");
      if (processGroupId !== undefined) stopProcessGroup(processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  15_000,
);

test("registry closure cannot miss a concurrent process registration", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
  const source = `
    const registry = await import(${JSON.stringify(registryUrl)});
    process.once("message", () => {
      let registered = false;
      try {
        registry.registerNotebookProcess(
          {
            ownerNonce: registry.createNotebookProcessOwnerNonce(),
            port: 4324,
            processGroupId: 123456,
          },
          { directory: ${JSON.stringify(directory)} },
        );
        registered = true;
      } catch {}
      process.send({ registered }, () => process.disconnect());
    });
  `;
  const worker = spawn(process.execPath, ["--input-type=module", "-e", source], {
    cwd: appDirectory,
    stdio: ["ignore", "ignore", "ignore", "ipc"],
  });
  try {
    const result = new Promise<boolean>((resolveResult, reject) => {
      worker.once("error", reject);
      worker.once("message", (message) =>
        resolveResult(registrationResultSchema.parse(message).registered),
      );
    });
    worker.send({ type: "register" });
    closeNotebookProcessRegistry({ directory });
    await Promise.all([
      result,
      stopRegisteredNotebookProcesses({
        directory,
        inspect: () => "stopped",
        isPortOpen: async () => false,
      }),
    ]);
    await waitForExit(worker);

    await expect(
      stopRegisteredNotebookProcesses({
        directory,
        inspect: () => "foreign",
        isPortOpen: async () => true,
      }),
    ).resolves.toBeUndefined();
  } finally {
    if (worker.exitCode === null && worker.signalCode === null) worker.kill("SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
});

test("normal teardown removes the exact process registration", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-processes-"));
  const ownerNonce = createNotebookProcessOwnerNonce();
  try {
    registerNotebookProcess({ ownerNonce, port: 4_324, processGroupId: 123_456 }, { directory });
    unregisterNotebookProcess({ ownerNonce, processGroupId: 123_456 }, { directory });

    await stopRegisteredNotebookProcesses({ directory });

    expect(existsSync(directory)).toBe(false);
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});

const receiptServer = `
  const { createServer } = require("node:http");
  const { writeFileSync, renameSync } = require("node:fs");
  const server = createServer((_request, response) => response.end("owned"));
  server.listen(0, "127.0.0.1", () => {
    const target = process.env.MARIMO_STUDIO_E2E_ENDPOINT_FILE;
    writeFileSync(target + ".tmp", JSON.stringify({
      ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER,
      pid: process.pid,
      port: server.address().port,
    }));
    renameSync(target + ".tmp", target);
  });
`;

test("an owned dynamic binding replaces its pending record and consumes the receipt", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
  const registration = startRegisteredNotebookProcess({
    command: process.execPath,
    args: ["-e", receiptServer],
    cwd: process.cwd(),
    directory,
    env: process.env,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.ready;
    const port = await registration.bound;
    expect(await responds(port)).toBe(true);
    const files = readdirSync(directory);
    expect(files).toEqual([`${registration.processGroupId}-${registration.ownerNonce}.json`]);
    expect(JSON.parse(readFileSync(resolve(directory, files[0]!), "utf8"))).toEqual({
      ownerNonce: registration.ownerNonce,
      processGroupId: registration.processGroupId,
      port,
    });
    registration.child.disconnect();
    await waitForExit(registration.child);
    expect(await responds(port)).toBe(false);
    expect(existsSync(directory)).toBe(false);
  } finally {
    stopProcessGroup(registration.processGroupId, "SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
}, 10_000);

test.each([
  ["stale owner", '{ ownerNonce: "0".repeat(64), pid: process.pid, port: 4321 }'],
  [
    "invalid port",
    "{ ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER, pid: process.pid, port: 0 }",
  ],
  [
    "dead process",
    "{ ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER, pid: 2147483647, port: 4321 }",
  ],
])(
  "rejects a %s endpoint receipt without registering its port",
  async (_name, payload) => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
    const script = `
    const { writeFileSync, renameSync } = require("node:fs");
    const target = process.env.MARIMO_STUDIO_E2E_ENDPOINT_FILE;
    writeFileSync(target + ".tmp", JSON.stringify(${payload}));
    renameSync(target + ".tmp", target);
    setInterval(() => {}, 1000);
  `;
    const registration = startRegisteredNotebookProcess({
      command: process.execPath,
      args: ["-e", script],
      cwd: process.cwd(),
      directory,
      env: process.env,
      stdio: ["ignore", "ignore", "ignore"],
    });
    try {
      await expect(registration.bound).rejects.toThrow("Invalid notebook endpoint receipt");
      await waitForExit(registration.child);
      expect(existsSync(directory)).toBe(false);
    } finally {
      stopProcessGroup(registration.processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  5_000,
);

test.each([
  ["exits", "process.exit(0)", 1000, "supervisor exited with status 0"],
  ["times out", "setInterval(() => {}, 1000)", 30, "binding timed out"],
])(
  "rejects pending binding and closes its watcher when the backend %s",
  async (_name, script, boundTimeout, message) => {
    const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
    const registration = startRegisteredNotebookProcess({
      command: process.execPath,
      args: ["-e", script],
      cwd: process.cwd(),
      directory,
      env: process.env,
      boundTimeout,
      stdio: ["ignore", "ignore", "ignore"],
    });
    try {
      await expect(registration.bound).rejects.toThrow(message);
      await waitForExit(registration.child);
      expect(existsSync(directory)).toBe(false);
    } finally {
      stopProcessGroup(registration.processGroupId, "SIGKILL");
      rmSync(directory, { force: true, recursive: true });
    }
  },
  5_000,
);

test("pending registrations never probe ports and cannot authorize an unverified signal", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
  const ownerNonce = createNotebookProcessOwnerNonce();
  const isPortOpen = vi.fn(async () => true);
  const stop = vi.fn();
  try {
    registerNotebookProcess({ ownerNonce, port: null, processGroupId: 123456 }, { directory });
    writeFileSync(resolve(directory, `123456-${ownerNonce}.endpoint.partial.tmp`), "partial");
    await expect(
      stopRegisteredNotebookProcesses({
        directory,
        inspect: () => "unknown",
        timeout: 50,
        isPortOpen,
        stop,
      }),
    ).rejects.toThrow("unknown owner");
    expect(stop).not.toHaveBeenCalled();
    expect(isPortOpen).not.toHaveBeenCalled();
    await stopRegisteredNotebookProcesses({
      directory,
      inspect: () => (stop.mock.calls.length ? "stopped" : "owned"),
      isPortOpen,
      stop,
    });
    expect(stop).toHaveBeenCalledExactlyOnceWith(123456, "SIGTERM");
    expect(isPortOpen).not.toHaveBeenCalled();
    expect(existsSync(directory)).toBe(false);
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});

test("registry closure rejects a delayed start before launching its backend", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
  const registration = spawnRegisteredNotebookSupervisor({
    command: process.execPath,
    args: ["-e", receiptServer],
    cwd: process.cwd(),
    directory,
    env: process.env,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.registered;
    closeNotebookProcessRegistry({ directory });
    await expect(registration.start()).rejects.toThrow("registry is closing");
    await expect(registration.bound).rejects.toThrow("registry is closing");
    await waitForExit(registration.child);
    expect(readdirSync(directory)).toEqual([".closing"]);
  } finally {
    stopProcessGroup(registration.processGroupId, "SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
}, 5_000);

test("reinspects an unknown pending owner until its exit is confirmed", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-e2e-binding-"));
  const ownerNonce = createNotebookProcessOwnerNonce();
  const inspect = vi
    .fn()
    .mockReturnValueOnce("unknown")
    .mockReturnValueOnce("unknown")
    .mockReturnValue("stopped");
  const stop = vi.fn();
  const isPortOpen = vi.fn();
  try {
    registerNotebookProcess({ ownerNonce, port: null, processGroupId: 123456 }, { directory });
    await stopRegisteredNotebookProcesses({ directory, inspect, stop, isPortOpen, timeout: 1000 });
    expect(stop).not.toHaveBeenCalled();
    expect(isPortOpen).not.toHaveBeenCalled();
    expect(existsSync(directory)).toBe(false);
  } finally {
    rmSync(directory, { force: true, recursive: true });
  }
});
