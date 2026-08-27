import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { expect, test } from "vite-plus/test";
import { z } from "zod";

import {
  closeNotebookProcessRegistry,
  createNotebookProcessOwnerNonce,
  registerNotebookProcess,
  stopRegisteredNotebookProcesses,
  unregisterNotebookProcess,
} from "../scripts/notebook-process-registry.mjs";
import { appDirectory } from "../scripts/paths.mjs";
import { processGroupIsRunning, stopProcessGroup } from "../scripts/process-group.mjs";
import { startRegisteredNotebookProcess } from "../scripts/registered-notebook-process.mjs";

const boundAddressSchema = z.object({ port: z.number().int().positive() });
const supervisorMessageSchema = z.object({ processGroupId: z.number().int().positive() });
const registrationResultSchema = z.object({ registered: z.boolean() });
const supportsProcessEnvironmentInspection =
  process.platform === "darwin" || process.platform === "linux";
const launcherUrl = pathToFileURL(
  resolve(appDirectory, "scripts/registered-notebook-process.mjs"),
).href;
const registryUrl = pathToFileURL(
  resolve(appDirectory, "scripts/notebook-process-registry.mjs"),
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
    .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
`;

const waitForSupervisor = (worker: ChildProcess) =>
  new Promise<number>((resolveGroup, reject) => {
    worker.once("error", reject);
    worker.once("message", (message) =>
      resolveGroup(supervisorMessageSchema.parse(message).processGroupId),
    );
  });

const waitForClose = (child: ChildProcess) =>
  child.exitCode !== null || child.signalCode !== null
    ? Promise.resolve()
    : new Promise<void>((resolveClose) => child.once("close", () => resolveClose()));

const workerSource = (directory: string, port: number, start: boolean) => `
  const launcher = await import(${JSON.stringify(launcherUrl)});
  const registration = launcher.${start ? "startRegisteredNotebookProcess" : "spawnRegisteredNotebookSupervisor"}({
    args: ["-e", ${JSON.stringify(signalResistantServer)}],
    command: process.execPath,
    cwd: process.cwd(),
    directory: ${JSON.stringify(directory)},
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: ${JSON.stringify(String(port))} },
    port: ${port},
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
      port,
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

      const closed = waitForClose(child);
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
      await waitForClose(worker);

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
      const disconnected = performance.now();
      worker.kill("SIGKILL");
      await waitForClose(worker);

      await expect.poll(() => responds(port)).toBe(false);
      await expect.poll(() => processGroupIsRunning(processGroupId)).toBe(false);
      expect(performance.now() - disconnected).toBeLessThan(1_000);
      await stopRegisteredNotebookProcesses({ directory, timeout: 100 });
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
    await waitForClose(worker);

    expect(readdirSync(directory).filter((name) => name.endsWith(".json"))).toEqual([]);
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
