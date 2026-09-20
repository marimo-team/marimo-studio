import type { IncomingMessage } from "node:http";
import type { Socket } from "node:net";

import { createHash, randomUUID } from "node:crypto";
import { createProxyServer, type ProxyServer } from "portless";
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
const networkIdentitySchema = z.object({
  runId: identitySchema,
  suite: identitySchema,
  workerId: identitySchema,
});
const listenerAddressSchema = z.object({ port: z.number().int().min(1).max(65535) });

export type E2ENetworkIdentity = z.infer<typeof networkIdentitySchema>;
export interface E2EEndpoint {
  readonly hostname: string;
  readonly port: number;
  readonly origin: string;
  readonly namedOrigin: string;
  bindBackend(port: number): () => void;
}
interface EndpointResource {
  hostname: string;
  server: ProxyServer | undefined;
  sockets: Set<Socket>;
  port: number;
  backend: { port: number } | undefined;
}
type NetworkState = "new" | "starting" | "running" | "closing" | "closed";

export const createE2ENetwork = (input: E2ENetworkIdentity) => {
  const { runId, suite, workerId } = networkIdentitySchema.parse(input);
  const runNamespace = [runId, suite, workerId].join("/");
  const suffix = createHash("sha256").update(runNamespace).digest("hex").slice(0, 20);
  let state: NetworkState = "new";
  let starting: Promise<void> | undefined;
  let closing: Promise<void> | undefined;
  const owned: EndpointResource[] = [];

  const requireRunning = () => {
    if (state !== "running") throw new Error(`E2E network is ${state}; await start() before use`);
  };
  const createEndpoint = (group: string, name: string): E2EEndpoint => {
    const hostname = `${group}-${name.toLowerCase()}.${suffix}.localhost`;
    const resource: EndpointResource = {
      hostname,
      server: undefined,
      sockets: new Set(),
      port: 0,
      backend: undefined,
    };
    owned.push(resource);
    return Object.freeze({
      hostname,
      get port() {
        requireRunning();
        return resource.port;
      },
      get origin() {
        requireRunning();
        return `http://127.0.0.1:${resource.port}`;
      },
      get namedOrigin() {
        requireRunning();
        return `http://${hostname}:${resource.port}`;
      },
      bindBackend(port: number) {
        requireRunning();
        if (!Number.isInteger(port) || port < 1 || port > 65535 || port === resource.port) {
          throw new RangeError("Backend port must identify a separate listening TCP server");
        }
        if (resource.backend !== undefined)
          throw new Error(`Backend already bound for ${hostname}`);
        const binding = { port };
        resource.backend = binding;
        return () => {
          if (resource.backend === binding) resource.backend = undefined;
        };
      },
    });
  };
  const createGroup = <Name extends string>(group: string, names: readonly Name[]) => {
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
      // Portless uses proxyPort only in unknown-host help links. The actual owned
      // listener address below supplies every fixture URL; no port is reserved/released.
      const server = createProxyServer({
        proxyPort: 0,
        getRoutes: () =>
          resource.backend === undefined
            ? []
            : [
                { hostname: "127.0.0.1", port: resource.backend.port },
                { hostname: "localhost", port: resource.backend.port },
                { hostname: resource.hostname, port: resource.backend.port },
              ],
      });
      // Portless opens an unpooled upstream connection for every HTTP request.
      // Native edit servers keep idle connections indefinitely; close each
      // upstream after its response, while leaving streams and upgrades live.
      server.prependListener("request", (request: IncomingMessage) => {
        request.headers.connection = "close";
      });
      resource.server = server;
      server.on("connection", (socket: Socket) => {
        resource.sockets.add(socket);
        socket.once("close", () => resource.sockets.delete(socket));
      });
      server.once("error", reject);
      server.listen(0, "127.0.0.1", () => {
        server.removeListener("error", reject);
        resource.port = listenerAddressSchema.parse(server.address()).port;
        resolve();
      });
    });

  const shutdown = async () => {
    const results = await Promise.allSettled(
      owned.map(async (resource) => {
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
  suite: process.env.MARIMO_STUDIO_E2E_SUITE ?? "main",
  workerId: process.env.TEST_WORKER_INDEX ?? "controller",
});
