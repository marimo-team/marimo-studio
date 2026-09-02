import { e2eNetwork } from "./network.mjs";

const port = 4_327 + e2eNetwork.portOffset;
const staticPort = 4_328 + e2eNetwork.portOffset;
const runPort = 4_329 + e2eNetwork.portOffset;
const readinessPath = "/_marimo-studio-ready";

export const installedPackageNetwork = Object.freeze({
  origin: `http://127.0.0.1:${port}`,
  port,
  static: Object.freeze({
    origin: `http://127.0.0.1:${staticPort}`,
    port: staticPort,
  }),
  readiness: Object.freeze({
    path: readinessPath,
    url: `http://127.0.0.1:${staticPort}${readinessPath}`,
  }),
  run: Object.freeze({
    origin: `http://127.0.0.1:${runPort}`,
    port: runPort,
  }),
});
