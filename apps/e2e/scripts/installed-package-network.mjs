import { e2eNetwork } from "./network.mjs";

const port = 4_327 + e2eNetwork.portOffset;

export const installedPackageNetwork = Object.freeze({
  origin: `http://127.0.0.1:${port}`,
  port,
});
