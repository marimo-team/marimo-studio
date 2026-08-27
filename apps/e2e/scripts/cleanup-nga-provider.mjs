import { rm } from "node:fs/promises";

import { providerConfigDirectory } from "./paths.mjs";
import { cleanNgaProviderWorkspace } from "./prepare-nga-provider.mjs";

export const cleanupNgaProviderEnvironment = async () => {
  await cleanNgaProviderWorkspace();
  await rm(providerConfigDirectory, {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 100,
  });
};
