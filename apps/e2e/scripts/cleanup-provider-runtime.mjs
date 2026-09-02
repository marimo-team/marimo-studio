import { rm } from "node:fs/promises";

import { providerConfigDirectory } from "./paths.mjs";
import { cleanProviderWorkspace } from "./prepare-provider-runtime.mjs";

export const cleanupProviderEnvironment = async () => {
  await cleanProviderWorkspace();
  await rm(providerConfigDirectory, {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 100,
  });
};
