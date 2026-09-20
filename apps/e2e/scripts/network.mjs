import { createHash, randomUUID } from "node:crypto";
import { createProxyServer } from "portless";
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
};

const identitySchema = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/, {
  message: "Network identity must be a nonempty portable identifier",
});
const networkIdentitySchema = z.object({
  runId: identitySchema,
  suite: identitySchema,
  workerId: identitySchema,
});
const listenerAddressSchema = z.object({ port: z.number().int().min(1).max(65535) });

export const createE2ENetwork = (input) => {
  const { runId, suite, workerId } = networkIdentitySchema.parse(input);
  const runNamespace = [runId, suite, workerId].join("/");
  const suffix = createHash("sha256").update(runNamespace).digest("hex").slice(0, 20);
  let state = "new";
  let starting;
  let closing;
  const owned = [];

  const requireRunning = () => {
    if (state !== "running") throw new Error(`E2E network is ${state}; await start() before use`);
  };
  const createEndpoint = (group, name) => {
    const hostname = `${group}-${name.toLowerCase()}.${suffix}.localhost`;
    const resource = {
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
      bindBackend(port) {
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
  /** @returns {Readonly<Record<string, ReturnType<typeof createEndpoint>>>} */
  const createGroup = (group, names) =>
    Object.freeze(Object.fromEntries(names.map((name) => [name, createEndpoint(group, name)])));
  const groups = {
    main: createGroup("main", endpointNames.main),
    provider: createGroup("provider", endpointNames.provider),
    installed: createGroup("installed", endpointNames.installed),
  };

  const startEndpoint = (resource) =>
    new Promise((resolve, reject) => {
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
      resource.server = server;
      server.on("connection", (socket) => {
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
        await new Promise((resolve, reject) => {
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
