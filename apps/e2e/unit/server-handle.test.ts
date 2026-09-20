import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { Writable } from "node:stream";
import { finished } from "node:stream/promises";
import { expect, test, vi } from "vite-plus/test";

import { createE2ENetwork } from "../scripts/network.ts";
import { NotebookServices } from "../scripts/notebook-services.ts";
import { portIsOpen } from "../scripts/process-group.ts";
import { ServerHandle } from "../scripts/server-process.ts";

const fixtureServer = `
      const {createServer} = require('node:http');
      const {writeFileSync, renameSync} = require('node:fs');
      const server = createServer((request, response) => {
        if (request.url.endsWith('/running_notebooks')) {
          response.end('{"files":[]}');
          return;
        }
        if (request.url.endsWith('/kernel/shutdown')) {
          response.end('ok');
          setImmediate(() => server.close(() => process.exit(Number(process.env.MARIMO_STUDIO_TEST_EXIT_CODE ?? 0))));
          return;
        }
        if (request.url.startsWith('/?file=')) {
          response.end('{"serverToken":"test-token"}');
          return;
        }
        if (request.url === '/missing') response.statusCode = 503;
        response.end('ready');
        if (request.url === '/output') console.log('captured output');
        if (request.url === '/exit') server.close(() => process.exit(0));
      });
      process.on('SIGTERM', () => server.close(() => process.exit(0)));
      server.listen(0, '127.0.0.1', () => {
        const target = process.env.MARIMO_STUDIO_E2E_ENDPOINT_FILE;
        writeFileSync(target + '.tmp', JSON.stringify({ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER, pid: process.pid, port: server.address().port}));
        renameSync(target + '.tmp', target);
      });
    `;

test("failed supervisor startup settles routed readiness without unhandled rejection", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "studio-routed-failure-"));
  const network = createE2ENetwork({ runId: "startup-failure", suite: "main", workerId: "one" });
  let unhandled = 0;
  const observe = () => {
    unhandled += 1;
  };
  process.on("unhandledRejection", observe);
  await network.start();
  const service = new ServerHandle({
    shutdown: "process",
    endpoint: network.main.studio,
    command: process.execPath,
    args: ["-e", ""],
    cwd: resolve(root, "missing"),
    directory: resolve(root, "registry"),
    env: process.env,
  });
  try {
    await expect(service.ready).rejects.toThrow("ENOENT");
    await expect(service.close({ timeout: 1000 })).rejects.toThrow();
    await new Promise<void>((done) => setImmediate(done));
    expect(unhandled).toBe(0);
    expect(service.child.pid).toBeUndefined();
  } finally {
    process.off("unhandledRejection", observe);
    await network.close();
    await rm(root, { recursive: true, force: true });
  }
});

test.each([
  "normal",
  "exit",
  "shutdown-crash",
  "forward-error",
  "held-forward-error",
  "forward-timeout",
])(
  "owns route and cleanup across %s",
  async (mode) => {
    const root = await mkdtemp(resolve(tmpdir(), "studio-server-owner-"));
    const network = createE2ENetwork({
      runId: "server-owner",
      suite: "main",
      workerId: mode,
    });
    await network.start();
    const heldWrite = Promise.withResolvers<(error?: Error | null) => void>();
    const holdOutput = mode === "held-forward-error" || mode === "forward-timeout";
    const forwardOutput = mode === "forward-error" || holdOutput;
    const forwarded = new Writable({
      write(_chunk, _encoding, callback) {
        if (holdOutput) heldWrite.resolve(callback);
        else callback(new Error("reporter closed"));
      },
    });
    const service = new ServerHandle({
      endpoint: network.main.studio,
      shutdown: mode === "shutdown-crash" || forwardOutput ? "studio" : "process",
      forward: forwardOutput ? { stdout: forwarded } : undefined,
      command: process.execPath,
      cwd: root,
      directory: resolve(root, "registry"),
      env: { ...process.env, MARIMO_STUDIO_TEST_EXIT_CODE: mode === "shutdown-crash" ? "1" : "0" },
      args: ["-e", fixtureServer],
    });
    try {
      await service.ready;
      expect(await (await fetch(service.serverUrl)).text()).toBe("ready");
      if (mode === "exit") {
        await (await fetch(`${service.serverUrl}/exit`)).body?.cancel();
        expect((await service.exited).message).toContain("exited unexpectedly with 0");
        await expect(service.close()).rejects.toThrow("exited unexpectedly");
      } else if (mode === "shutdown-crash") {
        await expect(service.close()).rejects.toThrow("exited unexpectedly with 1");
      } else if (holdOutput) {
        await (await fetch(`${service.serverUrl}/output`)).body?.cancel();
        const completeWrite = await heldWrite.promise;
        const childExited = new Promise<void>((resolve) =>
          service.child.once("exit", () => resolve()),
        );
        const closing = service.close({ timeout: 1000 });
        void closing.catch(() => undefined);
        try {
          await childExited;
          await Promise.all(
            [service.child.stdout, service.child.stderr].map((stream) =>
              stream ? finished(stream, { cleanup: true }) : Promise.resolve(),
            ),
          );
          if (mode === "forward-timeout") {
            await expect(closing).rejects.toThrow("Notebook forwarded output did not finish");
            const write = vi.spyOn(forwarded, "write");
            try {
              service.child.stdout?.emit("data", Buffer.from("late child output"));
              expect(write).not.toHaveBeenCalled();
            } finally {
              write.mockRestore();
            }
          }
        } finally {
          completeWrite(new Error("reporter closed"));
        }
        await new Promise<void>((resolve) => setImmediate(resolve));
        if (mode === "held-forward-error") await expect(closing).rejects.toThrow("reporter closed");
      } else if (mode === "forward-error") {
        await (await fetch(`${service.serverUrl}/output`)).body?.cancel();
        expect((await service.exited).message).toBe("reporter closed");
        expect(await (await fetch(service.serverUrl)).text()).toBe("ready");
        await expect(service.close()).rejects.toThrow("reporter closed");
      } else {
        const closing = service.close();
        expect(service.close()).toBe(closing);
        await closing;
      }
      expect(forwarded.listenerCount("error")).toBe(0);
      expect((await fetch(service.serverUrl)).status).toBe(404);
      expect(await portIsOpen(service.port)).toBe(false);
      expect(existsSync(resolve(root, "registry"))).toBe(false);
    } finally {
      await service.close().catch(() => undefined);
      await network.close();
      await rm(root, { recursive: true, force: true });
    }
  },
  15_000,
);

test("failed readiness contains the backend before start rejects", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "studio-services-start-"));
  const registry = resolve(root, "registry");
  const network = createE2ENetwork({ runId: "failed-readiness", suite: "main", workerId: "one" });
  const services = new NotebookServices(root, {
    command: process.execPath,
    prefix: [],
    cwd: root,
    registryDirectory: registry,
  });
  await network.start();
  try {
    await expect(
      services.start(["-e", fixtureServer], network.main.studio, "process", {
        readyUrl: `${network.main.studio.origin}/missing`,
        timeout: 100,
      }),
    ).rejects.toThrow("did not start");
    expect(existsSync(registry)).toBe(false);
    expect((await fetch(network.main.studio.origin)).status).toBe(404);
  } finally {
    await services.close();
    await network.close();
    await rm(root, { recursive: true, force: true });
  }
}, 15_000);
