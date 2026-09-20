import { once } from "node:events";
import { Agent, createServer, request, type Server } from "node:http";
import { connect, Server as NetServer, type Socket } from "node:net";
import { expect, test, vi } from "vite-plus/test";
import { z } from "zod";

import { createE2ENetwork } from "../scripts/network.ts";

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
    const endpoints = [first, second].flatMap((network) => Object.values(network.main));
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

test.each(["main", "provider", "installed"] as const)(
  "%s workers expose only their selected suite's listeners",
  async (suite) => {
    const network = createE2ENetwork({ runId: "suite-isolation", suite, workerId: "0" });
    try {
      await network.start();
      const endpoint = Object.values(network[suite])[0]!;
      expect(await status(endpoint.port)).toBe(404);
      expect(endpoint.origin).toBe(`http://127.0.0.1:${endpoint.port}`);
      const foreign = suite === "main" ? network.provider.live : network.main.studio;
      expect(() => foreign.port).toThrow("does not belong");
      expect(() => foreign.origin).toThrow("does not belong");
      expect(() => foreign.bindBackend(12345)).toThrow("does not belong");
    } finally {
      await network.close();
    }
  },
);

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
    socket.on("data", (chunk) => socket.write(chunk));
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
    const echoed = once(socket, "data");
    socket.write("upgraded payload");
    expect(String((await echoed)[0])).toBe("upgraded payload");
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

test("releases completed upstream connections while keeping streamed responses live", async () => {
  const network = createE2ENetwork({ runId: "upstream-lifetime", suite: "main", workerId: "0" });
  const sockets = new Set<Socket>();
  const server = createServer((incoming, response) => {
    if (incoming.url === "/events") {
      response.writeHead(200, { "content-type": "text/event-stream" });
      response.write("data: ready\n\n");
    } else {
      response.end("complete");
    }
  });
  server.keepAliveTimeout = 60_000;
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const agent = new Agent({ keepAlive: true, maxSockets: 4 });
  let streaming: ReturnType<typeof request> | undefined;
  try {
    await network.start();
    network.main.studio.bindBackend(z.object({ port: z.number() }).parse(server.address()).port);
    const options = { host: "127.0.0.1", port: network.main.studio.port, agent };
    const completed = () =>
      new Promise<{ status: number | undefined; body: string }>((resolve, reject) => {
        const call = request(options, (response) => {
          let body = "";
          response.on("data", (chunk) => (body += String(chunk)));
          response.once("error", reject);
          response.once("end", () => resolve({ status: response.statusCode, body }));
        });
        call.once("error", reject);
        call.end();
      });
    for (const response of await Promise.all(Array.from({ length: 12 }, completed))) {
      expect(response).toEqual({ status: 200, body: "complete" });
    }
    await expect.poll(() => sockets.size, { timeout: 1000 }).toBe(0);

    streaming = request({ ...options, path: "/events" });
    const received = once(streaming, "response");
    streaming.end();
    const [response] = await received;
    expect(response.statusCode).toBe(200);
    expect(String((await once(response, "data"))[0])).toBe("data: ready\n\n");
    expect(response.complete).toBe(false);
    expect(sockets.size).toBe(1);
    response.destroy();
    streaming.destroy();
    await expect.poll(() => sockets.size, { timeout: 1000 }).toBe(0);
  } finally {
    streaming?.destroy();
    agent.destroy();
    await network.close();
    await close(server);
  }
});

test("reports a running proxy failure and still releases every owned listener", async () => {
  const network = createE2ENetwork({ runId: "proxy-failure", suite: "main", workerId: "0" });
  const listening = vi.spyOn(NetServer.prototype, "listen");
  try {
    await network.start();
    const servers = listening.mock.contexts.map((server) => z.instanceof(NetServer).parse(server));
    const cause = new Error("accept failed");
    expect(() => servers[0]!.emit("error", cause)).not.toThrow();
    expect(() => network.main.studio.origin).toThrow("E2E proxy");
    await expect(network.close()).rejects.toMatchObject({ cause });
    expect(servers.every((server) => !server.listening)).toBe(true);
  } finally {
    listening.mockRestore();
    await network.close().catch(() => {});
  }
});
