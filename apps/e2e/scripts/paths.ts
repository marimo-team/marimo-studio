import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { e2eNetwork, type E2ENetworkIdentity } from "./network.ts";

const directory = dirname(fileURLToPath(import.meta.url));

export const appDirectory = resolve(directory, "..");
export const repositoryDirectory = resolve(appDirectory, "../..");
export const studioPackageDirectory = resolve(repositoryDirectory, "packages/marimo-studio");
export const fixtureDirectory = resolve(appDirectory, "fixtures");

export const createE2EPaths = (root: string, { runId, suite, workerId }: E2ENetworkIdentity) => {
  const resultRoot = resolve(root, "test-results", runId, suite, workerId);
  const workspaceDirectory = resolve(resultRoot, "workspace");
  return Object.freeze({
    resultRoot,
    blobReportDirectory: resolve(root, "test-results", `blob-${suite}`, runId, workerId),
    playwrightOutputDirectory: resolve(
      root,
      "test-results",
      `playwright-${suite}`,
      runId,
      workerId,
    ),
    configDirectory: resolve(resultRoot, "xdg-config"),
    workspaceDirectory,
    notebookProcessRegistryDirectory: resolve(workspaceDirectory, ".notebook-processes"),
    // Provider snapshots and npm packages need room below Windows' cwd path limit.
    providerWorkspaceDirectory: resolve(resultRoot, "provider"),
    providerStaticRoot: resolve(resultRoot, "provider-static"),
    providerConfigDirectory: resolve(resultRoot, "provider-config"),
    hostedWorkspaceDirectory: resolve(resultRoot, "workspaces", "hosted"),
  });
};

const mutable = createE2EPaths(appDirectory, e2eNetwork);

export const resultRoot = mutable.resultRoot;
export const blobReportDirectory = mutable.blobReportDirectory;
export const playwrightOutputDirectory = mutable.playwrightOutputDirectory;
export const configDirectory = mutable.configDirectory;
export const workspaceDirectory = mutable.workspaceDirectory;
export const notebookProcessRegistryDirectory = mutable.notebookProcessRegistryDirectory;
export const collaborativeWorkspaceDirectory = resolve(workspaceDirectory, "collaboration");
export const collaborativeNotebookPath = resolve(collaborativeWorkspaceDirectory, "notebook.py");
export const notebookPath = resolve(workspaceDirectory, "notebook.py");
export const noDisplayNotebookPath = resolve(workspaceDirectory, "no-display.py");
export const lazyNotebookPath = resolve(workspaceDirectory, "lazy.py");
export const staticExportDirectory = resolve(workspaceDirectory, "lazy-static");
export const noDisplayStaticExportDirectory = resolve(staticExportDirectory, "no-display");
export const providerWorkspaceDirectory = mutable.providerWorkspaceDirectory;
export const providerNotebookFixturePath = resolve(
  appDirectory,
  "fixtures-provider/projections.py",
);
export const providerNotebookPath = resolve(providerWorkspaceDirectory, "projections.py");
export const externalProviderPackage = resolve(appDirectory, "fixtures-provider/provider");
export const externalProviderNotebookFixture = resolve(
  appDirectory,
  "fixtures-provider/external.py",
);
export const externalProviderNotebookPath = resolve(providerWorkspaceDirectory, "external.py");
export const providerStaticRoot = mutable.providerStaticRoot;
export const providerConfigDirectory = mutable.providerConfigDirectory;
export const providerGalleryStaticDirectory = resolve(providerStaticRoot, "gallery");
export const providerStoryStaticDirectory = resolve(providerStaticRoot, "story");
export const providerWebStaticDirectory = resolve(providerStaticRoot, "web");
export const providerNotebookPreparedDirectory = resolve(providerStaticRoot, "notebook-prepared");
export const providerNotebookStaticDirectory = resolve(providerStaticRoot, "notebook");
export const providerRevealStaticDirectory = resolve(providerStaticRoot, "reveal");
export const hostedFixtureDirectory = resolve(appDirectory, "fixtures-hosted");
export const hostedWorkspaceDirectory = mutable.hostedWorkspaceDirectory;
export const hostedNotebookPath = resolve(hostedWorkspaceDirectory, "notebook.py");
