import { once } from "node:events";
import { createServer, request, type Server } from "node:http";
import { connect } from "node:net";
import { expect, test } from "vite-plus/test";
import { z } from "zod";

import { createE2ENetwork } from "../scripts/network.mjs";

const backend = async () => {
  const server = createServer((_request, response) => response.end("owned backend"));
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = z.object({ port: z.number() }).parse(server.address());
  return { server, port: address.port };
};

const close = async (server: Server) => {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
};

const status = (port: number, hostname = "127.0.0.1") =>
  new Promise<number | undefined>((resolve, reject) => {
    const call = request({ host: "127.0.0.1", port, headers: { host: hostname } }, (response) => {
      response.resume();
      response.once("end", () => resolve(response.statusCode));
    });
    call.once("error", reject);
    call.end();
  });

test("simultaneous workers own distinct listeners and bind routes only after backend readiness", async () => {
  const first = createE2ENetwork({ runId: "parallel-run", suite: "main", workerId: "0" });
  const second = createE2ENetwork({ runId: "parallel-run", suite: "main", workerId: "1" });
  const service = await backend();
  try {
    expect(() => first.main.studio.origin).toThrow("await start()");
    expect(() => first.main.studio.bindBackend(service.port)).toThrow("await start()");
    await Promise.all([first.start(), first.start(), second.start()]);
    const endpoints = [first, second].flatMap((network) => [
      ...Object.values(network.main),
      ...Object.values(network.provider),
      ...Object.values(network.installed),
    ]);
    const ports = endpoints.map((endpoint) => endpoint.port);
    expect(new Set(ports).size).toBe(ports.length);
    expect(ports).not.toContain(service.port);
    expect(first.runNamespace).not.toBe(second.runNamespace);
    expect(first.main.studio.hostname).not.toBe(second.main.studio.hostname);
    expect(await status(first.main.studio.port)).toBe(404);
    const release = first.main.studio.bindBackend(service.port);
    expect(await status(first.main.studio.port)).toBe(200);
    expect(await status(first.main.studio.port, "localhost")).toBe(200);
    expect(await status(first.main.studio.port, first.main.studio.hostname)).toBe(200);
    expect(await status(second.main.studio.port)).toBe(404);
    expect(() => first.main.studio.bindBackend(service.port)).toThrow("already bound");
    release();
    expect(await status(first.main.studio.port)).toBe(404);
    const replacement = first.main.studio.bindBackend(service.port);
    release();
    expect(await status(first.main.studio.port)).toBe(200);
    replacement();
    const retiredPort = first.main.studio.port;
    await first.close();
    await expect(status(retiredPort)).rejects.toThrow();
    expect(await status(service.port)).toBe(200);
    expect(() => first.main.studio.bindBackend(service.port)).toThrow("closed");
    await expect(first.start()).rejects.toThrow("closed");
  } finally {
    await Promise.all([first.close(), second.close()]);
    await close(service.server);
  }
});

test("closing during startup releases listeners and prevents later acquisitions", async () => {
  const network = createE2ENetwork({ runId: "closing-run", suite: "provider", workerId: "0" });
  const starting = network.start();
  const closing = network.close();
  await expect(starting).rejects.toThrow("startup did not complete");
  await closing;
  await network.close();
  expect(() => network.provider.live.port).toThrow("closed");
  await expect(network.start()).rejects.toThrow("closed");
});

test("network teardown closes upgraded sockets without stopping the backend", async () => {
  const network = createE2ENetwork({ runId: "upgraded-run", suite: "main", workerId: "0" });
  const service = await backend();
  service.server.on("upgrade", (_request, socket) => {
    socket.on("end", () => socket.destroy());
    socket.resume();
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n",
    );
  });
  await network.start();
  network.main.studio.bindBackend(service.port);
  const socket = connect(network.main.studio.port, "127.0.0.1");
  try {
    await once(socket, "connect");
    const response = once(socket, "data");
    socket.write(
      "GET / HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n",
    );
    expect(String((await response)[0])).toContain("101 Switching Protocols");
    const disconnected = once(socket, "close");
    await network.close();
    await disconnected;
    expect(await status(service.port)).toBe(200);
  } finally {
    socket.destroy();
    await network.close();
    await close(service.server);
  }
});

test("network identity cannot escape its run namespace", () => {
  for (const key of ["runId", "suite", "workerId"]) {
    expect(() =>
      createE2ENetwork({ runId: "run", suite: "main", workerId: "0", [key]: "../other" }),
    ).toThrow("portable identifier");
  }
});
