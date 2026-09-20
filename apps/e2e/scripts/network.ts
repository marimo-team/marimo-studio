import type { Socket } from "node:net";
import type { Duplex } from "node:stream";

import { createHash, randomUUID } from "node:crypto";
import { Agent, createServer, request, type IncomingMessage, type ServerResponse } from "node:http";
import { z } from "zod";

export const E2E_RUN_ID_ENV = "MARIMO_STUDIO_E2E_RUN_ID";

const endpointNames = {
  main: [
    "studio",
    "hosted",
    "exported",
    "recovery",
    "collaboration",
    "collaborationPeer",
    "forcedInterruption",
    "runInterruption",
    "hostSession",
  ],
  provider: [
    "live",
    "gallery",
    "story",
    "external",
    "web",
    "reveal",
    "notebook",
    "notebookPrepared",
  ],
  installed: ["edit", "fresh", "static", "run"],
} as const;

const identitySchema = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/, {
  message: "Network identity must be a nonempty portable identifier",
});
const suiteSchema = z.enum(["main", "provider", "installed"]);
const networkIdentitySchema = z.object({
  runId: identitySchema,
  suite: identitySchema.pipe(suiteSchema),
  workerId: identitySchema,
});
const listenerAddressSchema = z.object({ port: z.number().int().min(1).max(65535) });

export type E2ENetworkIdentity = z.infer<typeof networkIdentitySchema>;
export interface E2EEndpoint {
  readonly hostname: string;
  readonly port: number;
  readonly origin: string;
  bindBackend(port: number): () => void;
}
interface EndpointResource {
  hostname: string;
  server: ReturnType<typeof createServer> | undefined;
  sockets: Set<Socket>;
  port: number;
  backend: { port: number; agent: Agent } | undefined;
}
type NetworkState = "new" | "starting" | "running" | "closing" | "closed";

const MAX_UPSTREAM_SOCKETS = 8;
const UPSTREAM_IDLE_TIMEOUT = 250;

const responseHead = (upstream: IncomingMessage) => {
  const headers = upstream.rawHeaders
    .reduce<string[]>((lines, value, index, values) => {
      if (index % 2 === 0) lines.push(`${value}: ${values[index + 1]}`);
      return lines;
    }, [])
    .join("\r\n");
  return `HTTP/1.1 ${upstream.statusCode ?? 502} ${upstream.statusMessage ?? ""}\r\n${headers}\r\n\r\n`;
};

const forwardedHeaders = (incoming: IncomingMessage) => {
  const remoteAddress = incoming.socket.remoteAddress ?? "127.0.0.1";
  const forwardedFor = incoming.headers["x-forwarded-for"];
  return {
    ...incoming.headers,
    "x-forwarded-for": forwardedFor
      ? `${Array.isArray(forwardedFor) ? forwardedFor.join(", ") : forwardedFor}, ${remoteAddress}`
      : remoteAddress,
    "x-forwarded-host": incoming.headers["x-forwarded-host"] ?? incoming.headers.host,
    "x-forwarded-port":
      incoming.headers["x-forwarded-port"] ?? incoming.headers.host?.split(":").at(-1),
    "x-forwarded-proto": incoming.headers["x-forwarded-proto"] ?? "http",
  };
};

const forwardResponse = (upstream: IncomingMessage, response: ServerResponse) => {
  response.writeHead(upstream.statusCode ?? 502, upstream.headers);
  upstream.on("error", () => response.destroy());
  upstream.pipe(response);
};

const proxyRequest = (
  resource: EndpointResource,
  incoming: IncomingMessage,
  response: ServerResponse,
) => {
  const backend = resource.backend;
  if (backend === undefined) {
    response.writeHead(404, { "content-type": "text/plain" });
    response.end("No backend is bound to this endpoint.");
    return;
  }
  const upstream = request(
    {
      agent: backend.agent,
      headers: forwardedHeaders(incoming),
      hostname: "127.0.0.1",
      method: incoming.method,
      path: incoming.url,
      port: backend.port,
    },
    (upstreamResponse) => forwardResponse(upstreamResponse, response),
  );
  upstream.on("error", () => {
    if (response.headersSent) response.destroy();
    else {
      response.writeHead(502, { "content-type": "text/plain" });
      response.end("The endpoint backend is unavailable.");
    }
  });
  response.on("close", () => {
    if (!response.writableFinished && !upstream.destroyed) upstream.destroy();
  });
  incoming.on("error", () => upstream.destroy());
  incoming.pipe(upstream);
};

const proxyUpgrade = (
  resource: EndpointResource,
  incoming: IncomingMessage,
  socket: Duplex,
  head: Buffer,
) => {
  const backend = resource.backend;
  if (backend === undefined) {
    socket.destroy();
    return;
  }
  const upstream = request({
    agent: backend.agent,
    headers: forwardedHeaders(incoming),
    hostname: "127.0.0.1",
    method: incoming.method,
    path: incoming.url,
    port: backend.port,
  });
  let upgraded = false;
  const close = () => {
    upstream.destroy();
    socket.destroy();
  };
  upstream.on("upgrade", (upstreamResponse, upstreamSocket, upstreamHead) => {
    upgraded = true;
    socket.write(responseHead(upstreamResponse));
    if (upstreamHead.length > 0) socket.write(upstreamHead);
    if (head.length > 0) upstreamSocket.write(head);
    upstreamSocket.pipe(socket);
    socket.pipe(upstreamSocket);
    const closeUpgrade = () => {
      upstreamSocket.destroy();
      socket.destroy();
    };
    upstreamSocket.on("error", closeUpgrade);
    upstreamSocket.on("close", closeUpgrade);
    upstreamSocket.on("end", closeUpgrade);
    socket.on("close", closeUpgrade);
    socket.on("end", closeUpgrade);
  });
  upstream.on("response", (upstreamResponse) => {
    upgraded = true;
    socket.write(responseHead(upstreamResponse));
    upstreamResponse.pipe(socket);
  });
  upstream.on("error", close);
  socket.on("error", close);
  socket.on("close", () => {
    if (!upgraded) upstream.destroy();
  });
  upstream.end();
};

export const createE2ENetwork = (input: E2ENetworkIdentity) => {
  const { runId, suite, workerId } = networkIdentitySchema.parse(input);
  const runNamespace = [runId, suite, workerId].join("/");
  const suffix = createHash("sha256").update(runNamespace).digest("hex").slice(0, 20);
  let state: NetworkState = "new";
  let starting: Promise<void> | undefined;
  let closing: Promise<void> | undefined;
  let failure: Error | undefined;
  const owned: EndpointResource[] = [];

  const requireRunning = (group: keyof typeof endpointNames) => {
    if (failure) throw failure;
    if (group !== suite) throw new Error(`${group} endpoint does not belong to ${suite} suite`);
    if (state !== "running") throw new Error(`E2E network is ${state}; await start() before use`);
  };
  const createEndpoint = (group: keyof typeof endpointNames, name: string): E2EEndpoint => {
    const hostname = `${group}-${name.toLowerCase()}.${suffix}.localhost`;
    const resource: EndpointResource = {
      hostname,
      server: undefined,
      sockets: new Set(),
      port: 0,
      backend: undefined,
    };
    if (group === suite) owned.push(resource);
    return Object.freeze({
      hostname,
      get port() {
        requireRunning(group);
        return resource.port;
      },
      get origin() {
        requireRunning(group);
        return `http://127.0.0.1:${resource.port}`;
      },
      bindBackend(port: number) {
        requireRunning(group);
        if (!Number.isInteger(port) || port < 1 || port > 65535 || port === resource.port) {
          throw new RangeError("Backend port must identify a separate listening TCP server");
        }
        if (resource.backend !== undefined)
          throw new Error(`Backend already bound for ${hostname}`);
        const binding = {
          port,
          agent: new Agent({
            keepAlive: true,
            maxFreeSockets: MAX_UPSTREAM_SOCKETS,
            maxSockets: MAX_UPSTREAM_SOCKETS,
            timeout: UPSTREAM_IDLE_TIMEOUT,
          }),
        };
        resource.backend = binding;
        return () => {
          if (resource.backend !== binding) return;
          resource.backend = undefined;
          binding.agent.destroy();
        };
      },
    });
  };
  const createGroup = <Name extends string>(
    group: keyof typeof endpointNames,
    names: readonly Name[],
  ) => {
    // SAFETY: Each name from the fixed catalog becomes a key with exactly one endpoint.
    return Object.freeze(
      Object.fromEntries(names.map((name) => [name, createEndpoint(group, name)])),
    ) as Readonly<Record<Name, E2EEndpoint>>;
  };
  const groups = {
    main: createGroup("main", endpointNames.main),
    provider: createGroup("provider", endpointNames.provider),
    installed: createGroup("installed", endpointNames.installed),
  };

  const startEndpoint = (resource: EndpointResource) =>
    new Promise<void>((resolve, reject) => {
      const server = createServer((incoming, response) =>
        proxyRequest(resource, incoming, response),
      );
      server.on("upgrade", (incoming, socket, head) =>
        proxyUpgrade(resource, incoming, socket, head),
      );
      resource.server = server;
      server.on("connection", (socket: Socket) => {
        resource.sockets.add(socket);
        socket.once("close", () => resource.sockets.delete(socket));
      });
      server.on("error", (cause: Error) => {
        failure ??= new Error(`E2E proxy ${resource.hostname} failed`, { cause });
        reject(failure);
      });
      server.listen(0, "127.0.0.1", () => {
        resource.port = listenerAddressSchema.parse(server.address()).port;
        resolve();
      });
    });

  const shutdown = async () => {
    const results = await Promise.allSettled(
      owned.map(async (resource) => {
        resource.backend?.agent.destroy();
        resource.backend = undefined;
        const server = resource.server;
        if (!server?.listening) return;
        await new Promise<void>((resolve, reject) => {
          const deadline = setTimeout(() => reject(new Error("E2E proxy did not close")), 1000);
          for (const socket of resource.sockets) socket.destroy();
          server.close((error) => {
            clearTimeout(deadline);
            if (error) reject(error);
            else resolve();
          });
        });
      }),
    );
    const errors = results.flatMap((result) =>
      result.status === "rejected" ? [result.reason] : [],
    );
    if (errors.length) throw new AggregateError(errors, "E2E proxy cleanup failed");
  };

  return Object.freeze({
    runId,
    suite,
    workerId,
    runNamespace,
    ...groups,
    start() {
      if (state === "closing" || state === "closed")
        return Promise.reject(new Error("E2E network is closed"));
      if (starting) return starting;
      state = "starting";
      starting = (async () => {
        const results = await Promise.allSettled(owned.map(startEndpoint));
        const errors = results.flatMap((result) =>
          result.status === "rejected" ? [result.reason] : [],
        );
        if (failure && !errors.includes(failure)) errors.push(failure);
        if (errors.length || state !== "starting") {
          state = "closing";
          try {
            await shutdown();
          } finally {
            state = "closed";
          }
          throw new AggregateError(errors, "E2E network startup did not complete");
        }
        state = "running";
      })();
      return starting;
    },
    close() {
      if (closing) return closing;
      state = "closing";
      closing = (async () => {
        try {
          await starting?.catch(() => {});
          await shutdown();
          if (failure) throw failure;
        } finally {
          state = "closed";
        }
      })();
      return closing;
    },
  });
};

const runId = process.env[E2E_RUN_ID_ENV] ?? randomUUID();
process.env[E2E_RUN_ID_ENV] = runId;
export const e2eNetwork = createE2ENetwork({
  runId,
  suite: suiteSchema.parse(process.env.MARIMO_STUDIO_E2E_SUITE ?? "main"),
  workerId: process.env.TEST_WORKER_INDEX ?? "controller",
});
