import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";
import { z } from "zod";

import { requestStudioShutdown } from "../scripts/graceful-shutdown.mjs";
import { unregisterNotebookProcess } from "../scripts/notebook-process-registry.mjs";
import { fixtureDirectory } from "../scripts/paths.mjs";
import { processGroupIsRunning, stopProcessGroup } from "../scripts/process-group.mjs";
import { startRegisteredNotebookProcess } from "../scripts/registered-notebook-process.mjs";
import {
  assertNoLeakedSemaphoreWarning,
  stopNotebookProcess,
  verifyNotebookProcessOutput,
  waitForServer,
} from "../scripts/server-process.mjs";
import {
  type NotebookServer,
  closeFailedNotebookServer,
  notebookServerPortIsOpen,
  startNotebookServer,
  stopNotebookServer,
  waitForNotebookServer,
} from "../tests/notebook-server.ts";

const boundAddressSchema = z.object({ port: z.number().int().positive() });
const FIXTURE_SERVER_START_TIMEOUT = 5_000;
const PROBE_TIMEOUT = 500;
const NATIVE_SERVER_START_TIMEOUT = 15_000;
const posixTest = process.platform === "win32" ? test.skip : test;

const expectProcessTreeRootStopped = (
  child: ReturnType<typeof spawn>,
  processGroupId: number | undefined,
) => {
  if (processGroupId !== undefined) {
    const groupRunning = processGroupIsRunning(processGroupId);
    if (groupRunning !== undefined) expect(groupRunning).toBe(false);
  }
  expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
};

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

const notebookProcessRecords = (directory: string) =>
  existsSync(directory) ? readdirSync(directory).filter((name) => name.endsWith(".json")) : [];

test("rejects Python resource tracker semaphore leaks", () => {
  expect(() =>
    assertNoLeakedSemaphoreWarning(
      "/python/resource_tracker.py:254: UserWarning: resource_tracker: " +
        "There appear to be 12 leaked semaphore objects to clean up at shutdown\n",
    ),
  ).toThrow("Notebook server leaked semaphore objects during shutdown");
});

test.each([
  "",
  "intentional negative-path traceback\n",
  "resource_tracker: There appear to be 2 leaked shared_memory objects to clean up at shutdown\n",
])("accepts clean and unrelated notebook stderr", (output) => {
  expect(() => assertNoLeakedSemaphoreWarning(output)).not.toThrow();
});

test("waits for final process output before checking semaphore leaks", async () => {
  let output = "resource_tracker: There appear to be 3 leaked sema";
  const closed = Promise.resolve().then(() => {
    output += "phore objects to clean up at shutdown";
  });

  await expect(verifyNotebookProcessOutput(closed, () => output)).rejects.toThrow(
    "Notebook server leaked semaphore objects during shutdown",
  );
});

test("authenticates and drains every session before hosted shutdown", async () => {
  const requests: Array<{
    authorization?: string;
    body?: string;
    path: string;
    serverToken?: string;
  }> = [];
  const sessions = new Set(["session-a", "session-b"]);
  const server = createHttpServer(async (request, response) => {
    const serverToken = request.headers["marimo-server-token"];
    let body = "";
    for await (const chunk of request) body += chunk.toString();
    requests.push({
      authorization: request.headers.authorization,
      body: body || undefined,
      path: request.url ?? "",
      serverToken: Array.isArray(serverToken) ? serverToken[0] : serverToken,
    });
    if (request.method === "GET") {
      response.end('{"serverToken":"server-token"}');
      return;
    }
    if (request.url?.endsWith("/running_notebooks")) {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ files: [...sessions].map((sessionId) => ({ sessionId })) }));
      return;
    }
    if (request.url?.endsWith("/shutdown_session")) {
      sessions.delete(z.object({ sessionId: z.string() }).parse(JSON.parse(body)).sessionId);
      response.end("ok");
      return;
    }
    response.end("ok");
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = boundAddressSchema.parse(server.address());

  try {
    await requestStudioShutdown(`http://127.0.0.1:${address.port}/hosted`, "access-token");
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error === undefined ? resolve() : reject(error)));
    });
  }

  expect(requests).toEqual([
    {
      authorization: "Bearer access-token",
      body: undefined,
      path: "/hosted/?file=notebook.py",
      serverToken: undefined,
    },
    {
      authorization: "Bearer access-token",
      body: undefined,
      path: "/hosted/api/home/running_notebooks",
      serverToken: "server-token",
    },
    {
      authorization: "Bearer access-token",
      body: '{"sessionId":"session-a"}',
      path: "/hosted/api/home/shutdown_session",
      serverToken: "server-token",
    },
    {
      authorization: "Bearer access-token",
      body: '{"sessionId":"session-b"}',
      path: "/hosted/api/home/shutdown_session",
      serverToken: "server-token",
    },
    {
      authorization: "Bearer access-token",
      body: undefined,
      path: "/hosted/api/home/running_notebooks",
      serverToken: "server-token",
    },
    {
      authorization: "Bearer access-token",
      body: undefined,
      path: "/hosted/api/kernel/shutdown",
      serverToken: "server-token",
    },
  ]);
});

test("rejects a failed graceful-shutdown bootstrap request", async () => {
  const server = createHttpServer((_request, response) => {
    response.statusCode = 503;
    response.end('{"serverToken":"stale-token"}');
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = boundAddressSchema.parse(server.address());

  try {
    await expect(requestStudioShutdown(`http://127.0.0.1:${address.port}`)).rejects.toThrow(
      "Marimo bootstrap returned 503",
    );
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error === undefined ? resolve() : reject(error)));
    });
  }
});

test("reports bootstrap failure after containing the registered notebook process", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-bootstrap-failure-"));
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((_request, response) => {
      response.statusCode = 503;
      response.end("unavailable");
    }).listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const registration = startRegisteredNotebookProcess({
    args: ["-e", source],
    command: process.execPath,
    cwd: process.cwd(),
    directory,
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    port,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.ready;
    await expect
      .poll(
        async () => {
          try {
            const response = await fetch(`http://127.0.0.1:${port}`, {
              signal: AbortSignal.timeout(PROBE_TIMEOUT),
            });
            await response.body?.cancel();
            return response.status;
          } catch {
            return 0;
          }
        },
        { timeout: FIXTURE_SERVER_START_TIMEOUT },
      )
      .toBe(503);
    await expect(
      stopNotebookProcess(
        {
          child: registration.child,
          port,
          processGroupId: registration.processGroupId,
          serverUrl: `http://127.0.0.1:${port}`,
        },
        { shutdown: "studio", timeout: 100 },
      ),
    ).rejects.toThrow("Marimo bootstrap returned 503");

    expectProcessTreeRootStopped(registration.child, registration.processGroupId);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
    unregisterNotebookProcess(registration, { directory });
    expect(existsSync(directory)).toBe(false);
  } finally {
    stopProcessGroup(registration.processGroupId, "SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
}, 10_000);

test("run shutdown owns the full grace period before forcing a resistant group", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-run-grace-"));
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((_request, response) => response.end("ready"))
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const registration = startRegisteredNotebookProcess({
    args: ["-e", source],
    command: process.execPath,
    cwd: process.cwd(),
    directory,
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    port,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.ready;
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    const started = performance.now();
    await stopNotebookProcess(
      {
        child: registration.child,
        port,
        processGroupId: registration.processGroupId,
        serverUrl: `http://127.0.0.1:${port}`,
      },
      { shutdown: "run", timeout: 750 },
    );

    expect(performance.now() - started).toBeGreaterThanOrEqual(650);
    expectProcessTreeRootStopped(registration.child, registration.processGroupId);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
    unregisterNotebookProcess(registration, { directory });
    expect(existsSync(directory)).toBe(false);
  } finally {
    stopProcessGroup(registration.processGroupId, "SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
}, 10_000);

const delayedCooperativeKernelExit = async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "marimo-studio-run-cooperative-"));
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    const server = createServer((_request, response) => response.end("ready"));
    let stopping = false;
    process.on("SIGTERM", () => {
      if (stopping) return;
      stopping = true;
      setTimeout(() => server.close(() => process.exit(0)), 400);
    });
    server.listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const registration = startRegisteredNotebookProcess({
    args: ["-e", source],
    command: process.execPath,
    cwd: process.cwd(),
    directory,
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    port,
    stdio: ["ignore", "ignore", "ignore"],
  });
  try {
    await registration.ready;
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    const started = performance.now();
    await stopNotebookProcess(
      {
        child: registration.child,
        port,
        processGroupId: registration.processGroupId,
        serverUrl: `http://127.0.0.1:${port}`,
      },
      { shutdown: "run", timeout: 1_500 },
    );

    const elapsed = performance.now() - started;
    expect(elapsed).toBeGreaterThanOrEqual(350);
    expect(elapsed).toBeLessThan(1_200);
    expect(processGroupIsRunning(registration.processGroupId)).toBe(false);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
    unregisterNotebookProcess(registration, { directory });
    expect(existsSync(directory)).toBe(false);
  } finally {
    stopProcessGroup(registration.processGroupId, "SIGKILL");
    rmSync(directory, { force: true, recursive: true });
  }
};
posixTest(
  "run shutdown lets a delayed cooperative kernel exit inside its grace period",
  delayedCooperativeKernelExit,
  15_000,
);

test("stops a native authenticated Marimo run server without Studio bootstrap", async () => {
  const root = mkdtempSync(resolve(tmpdir(), "marimo-studio-run-wrapper-"));
  try {
    const workspace = resolve(root, "workspace");
    const registryDirectory = resolve(root, "registry");
    mkdirSync(workspace);
    cpSync(resolve(fixtureDirectory, "plain.py"), resolve(workspace, "plain.py"));
    const port = await availablePort();
    const server = startNotebookServer({
      authentication: ["--token-password", "run-access-token"],
      command: "run",
      extensions: "native",
      port,
      registryDirectory,
      target: resolve(workspace, "plain.py"),
    });
    let stopped = false;
    try {
      await waitForNotebookServer(server, `${server.serverUrl}/?access_token=run-access-token`, {
        timeout: NATIVE_SERVER_START_TIMEOUT,
      });
      const studioAsset = await fetch(
        `${server.serverUrl}/_marimo-studio/views/assets/runtime.js?access_token=run-access-token`,
        {
          redirect: "manual",
          signal: AbortSignal.timeout(PROBE_TIMEOUT),
        },
      );
      await studioAsset.body?.cancel();
      expect(studioAsset.status).toBe(404);
      await stopNotebookServer(server, { timeout: 2_000 });
      stopped = true;

      expect(() => assertNoLeakedSemaphoreWarning(server.output())).not.toThrow();
    } finally {
      const cleanupFailure = !stopped
        ? await closeFailedNotebookServer(server, { timeout: 2_000 })
        : undefined;
      expect.soft(cleanupFailure).toBeUndefined();
      expectProcessTreeRootStopped(server.process, server.processGroupId);
      expect(await notebookServerPortIsOpen(port)).toBe(false);
      expect(notebookProcessRecords(registryDirectory)).toEqual([]);
    }
  } finally {
    rmSync(root, { force: true, recursive: true });
  }
}, 30_000);

test("reports a signal exit immediately while waiting for startup", async () => {
  const child = {
    exitCode: null,
    signalCode: "SIGTERM",
  };
  let requests = 0;

  await expect(
    waitForServer(child, "http://127.0.0.1:1", {
      timeout: 1_000,
      request: async () => {
        requests += 1;
        throw new Error("Readiness request must not start after process exit");
      },
    }),
  ).rejects.toThrow("exited during startup with signal SIGTERM");
  expect(requests).toBe(0);
});

test("bounds a readiness request that never returns headers", async () => {
  const server = createHttpServer(() => {});
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = boundAddressSchema.parse(server.address());
  try {
    await expect(
      waitForServer({ exitCode: null, signalCode: null }, `http://127.0.0.1:${address.port}`, {
        timeout: 100,
      }),
    ).rejects.toThrow("did not start");
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error === undefined ? resolve() : reject(error)));
    });
  }
});

const stopListeningDescendant = async () => {
  const port = await availablePort();
  const descendant = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((request, response) => {
      if (request.method === "GET") {
        response.end('<script>{"serverToken":"server-token"}</script>');
      } else if (request.url.endsWith("/running_notebooks")) {
        response.end('{"files":[]}');
      } else {
        response.end("ok");
      }
    })
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const wrapper = `
    const { spawn } = require("node:child_process");
    spawn(process.execPath, ["-e", ${JSON.stringify(descendant)}], { stdio: "ignore" });
    process.exit(0);
  `;
  const child = spawn(process.execPath, ["-e", wrapper], {
    detached: process.platform !== "win32",
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    stdio: "ignore",
  });
  const server: NotebookServer = {
    authToken: undefined,
    output: () => "",
    port,
    process: child,
    processGroupId: child.pid,
    ready: Promise.resolve(),
    serverUrl: `http://127.0.0.1:${port}`,
    shutdown: "studio",
  };

  try {
    await new Promise<void>((resolve) => child.once("close", () => resolve()));
    expect(child.exitCode).toBe(0);
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    await stopNotebookServer(server);
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
  } finally {
    if (child.pid !== undefined) {
      stopProcessGroup(child.pid, "SIGKILL");
    }
  }
};
posixTest("stops a listening descendant after its wrapper exits", stopListeningDescendant, 20_000);

test("forces shutdown when the graceful endpoint leaves the server alive", async () => {
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((request, response) => {
      if (request.method === "GET") {
        response.end('<script>{"serverToken":"server-token"}</script>');
      } else if (request.url.endsWith("/running_notebooks")) {
        response.end('{"files":[]}');
      } else {
        response.end("ok");
      }
    }).listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const child = spawn(process.execPath, ["-e", source], {
    detached: process.platform !== "win32",
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    stdio: "ignore",
  });

  try {
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    await stopNotebookProcess(
      {
        child,
        port,
        serverUrl: "http://127.0.0.1:" + port,
      },
      { shutdown: "studio", timeout: 100 },
    );
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
  } finally {
    if (child.pid !== undefined) {
      stopProcessGroup(child.pid, "SIGKILL");
    }
  }
}, 10_000);

test("reports a session drain failure after forcing the server process closed", async () => {
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((request, response) => {
      if (request.method === "GET") {
        response.end('<script>{"serverToken":"server-token"}</script>');
      } else if (request.url.endsWith("/running_notebooks")) {
        response.statusCode = 503;
        response.end("unavailable");
      } else {
        response.end("ok");
      }
    }).listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const child = spawn(process.execPath, ["-e", source], {
    detached: process.platform !== "win32",
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    stdio: "ignore",
  });

  try {
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    await expect(
      stopNotebookProcess(
        {
          child,
          port,
          serverUrl: "http://127.0.0.1:" + port,
        },
        { shutdown: "studio", timeout: 100 },
      ),
    ).rejects.toThrow("Marimo session inventory returned 503");
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
  } finally {
    if (child.pid !== undefined) {
      stopProcessGroup(child.pid, "SIGKILL");
    }
  }
}, 10_000);

test("forces a signal-resistant static server to exit", async () => {
  const port = await availablePort();
  const source = `
    const { createServer } = require("node:http");
    process.on("SIGTERM", () => {});
    createServer((_request, response) => response.end("static"))
      .listen(Number(process.env.MARIMO_STUDIO_TEST_PORT), "127.0.0.1");
  `;
  const child = spawn(process.execPath, ["-e", source], {
    detached: process.platform !== "win32",
    env: { ...process.env, MARIMO_STUDIO_TEST_PORT: String(port) },
    stdio: "ignore",
  });

  try {
    await expect.poll(() => responds(port), { timeout: FIXTURE_SERVER_START_TIMEOUT }).toBe(true);
    await stopNotebookProcess(
      {
        child,
        port,
        serverUrl: "http://127.0.0.1:" + port,
      },
      { shutdown: "process", timeout: 100 },
    );
    expect(child.exitCode !== null || child.signalCode !== null).toBe(true);
    expect(await notebookServerPortIsOpen(port)).toBe(false);
  } finally {
    if (child.pid !== undefined) {
      stopProcessGroup(child.pid, "SIGKILL");
    }
  }
}, 10_000);
