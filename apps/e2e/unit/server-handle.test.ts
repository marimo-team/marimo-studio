import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { createE2ENetwork } from "../scripts/network.ts";
import { portIsOpen } from "../scripts/process-group.ts";
import { ServerHandle } from "../scripts/server-process.ts";

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
    await expect(service.ready).rejects.toThrow("process group ID");
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

test.each([false, true])("owns route and cleanup across unexpected exit=%s", async (unexpected) => {
  const root = await mkdtemp(resolve(tmpdir(), "studio-server-owner-"));
  const network = createE2ENetwork({
    runId: "server-owner",
    suite: "main",
    workerId: String(unexpected),
  });
  await network.start();
  const service = new ServerHandle({
    endpoint: network.main.studio,
    shutdown: "process",
    command: process.execPath,
    cwd: root,
    directory: resolve(root, "registry"),
    env: process.env,
    args: [
      "-e",
      `
      const {createServer} = require('node:http');
      const {writeFileSync} = require('node:fs');
      const server = createServer((request, response) => {
        response.end('ready');
        if (request.url === '/exit') server.close(() => process.exit(0));
      });
      process.on('SIGTERM', () => server.close(() => process.exit(0)));
      server.listen(0, '127.0.0.1', () => writeFileSync(process.env.MARIMO_STUDIO_E2E_ENDPOINT_FILE,
        JSON.stringify({ownerNonce: process.env.MARIMO_STUDIO_E2E_PROCESS_OWNER, pid: process.pid, port: server.address().port})));
    `,
    ],
  });
  try {
    await service.ready;
    expect(await (await fetch(service.serverUrl)).text()).toBe("ready");
    if (unexpected) {
      await (await fetch(`${service.serverUrl}/exit`)).body?.cancel();
      expect((await service.exited).message).toContain("exited unexpectedly with 0");
      await expect(service.close()).rejects.toThrow("exited unexpectedly");
    } else {
      const closing = service.close();
      expect(service.close()).toBe(closing);
      await closing;
    }
    expect((await fetch(service.serverUrl)).status).toBe(404);
    expect(await portIsOpen(service.port)).toBe(false);
    expect(existsSync(resolve(root, "registry"))).toBe(false);
  } finally {
    await service.close().catch(() => undefined);
    await network.close();
    await rm(root, { recursive: true, force: true });
  }
});
