import { cp, rm } from "node:fs/promises";
import { resolve } from "node:path";

import { externalProviderPackage } from "./paths.mjs";

export const copyFixtureProviderPackage = async (workspace) => {
  const destination = resolve(workspace, "../fixtures-provider/provider");
  if (destination === externalProviderPackage) return;
  await rm(destination, {
    force: true,
    maxRetries: 5,
    recursive: true,
    retryDelay: 100,
  });
  await cp(externalProviderPackage, destination, { recursive: true });
};
