import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

import { copyFixtureProviderPackage } from "./fixture-provider-package.ts";
import { collaborativeWorkspaceDirectory, fixtureDirectory } from "./paths.ts";

export const prepareCollaborativeWorkspace = async () => {
  await rm(collaborativeWorkspaceDirectory, {
    force: true,
    maxRetries: 5,
    recursive: true,
    retryDelay: 100,
  });
  await mkdir(collaborativeWorkspaceDirectory, { recursive: true });
  await cp(
    resolve(fixtureDirectory, "notebook.py"),
    resolve(collaborativeWorkspaceDirectory, "notebook.py"),
  );
  await cp(
    resolve(fixtureDirectory, "__marimo__/studio/notebook"),
    resolve(collaborativeWorkspaceDirectory, "__marimo__/studio/notebook"),
    { recursive: true },
  );
  await copyFixtureProviderPackage(collaborativeWorkspaceDirectory);
};
