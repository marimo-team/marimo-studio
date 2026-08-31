import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { e2eNetwork } from "./network.mjs";

const directory = dirname(fileURLToPath(import.meta.url));

export const appDirectory = resolve(directory, "..");
export const repositoryDirectory = resolve(appDirectory, "../..");
export const studioPackageDirectory = resolve(repositoryDirectory, "packages/marimo-studio");
export const fixtureDirectory = resolve(appDirectory, "fixtures");

export const createE2EPaths = (root, portOffset = 0) => {
  const resultRoot =
    portOffset === 0
      ? resolve(root, "test-results")
      : resolve(root, "test-results", `offset-${portOffset}`);
  const workspaceDirectory =
    portOffset === 0 ? resolve(root, ".workspace") : resolve(resultRoot, "workspace");
  const providerWorkspaceRoot = resolve(resultRoot, "workspaces");
  return Object.freeze({
    configDirectory: resolve(resultRoot, "xdg-config"),
    workspaceDirectory,
    notebookProcessRegistryDirectory: resolve(workspaceDirectory, ".notebook-processes"),
    providerWorkspaceDirectory: resolve(providerWorkspaceRoot, "provider-runtime"),
    providerStaticRoot: resolve(providerWorkspaceRoot, "provider-runtime-static"),
    providerConfigDirectory: resolve(providerWorkspaceRoot, "provider-runtime-xdg-config"),
    hostedWorkspaceDirectory: resolve(providerWorkspaceRoot, "hosted"),
    mainPlaywrightOutputDirectory:
      portOffset === 0 ? resultRoot : resolve(resultRoot, "playwright-main"),
    providerPlaywrightOutputDirectory:
      portOffset === 0 ? resultRoot : resolve(resultRoot, "playwright-provider"),
    mainPlaywrightReportDirectory:
      portOffset === 0 ? resolve(root, "playwright-report") : resolve(resultRoot, "report-main"),
    providerPlaywrightReportDirectory:
      portOffset === 0
        ? resolve(root, "playwright-report")
        : resolve(resultRoot, "report-provider"),
  });
};

const mutable = createE2EPaths(appDirectory, e2eNetwork.portOffset);

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
export const hostedFixtureDirectory = resolve(appDirectory, "fixtures-hosted");
export const hostedWorkspaceDirectory = mutable.hostedWorkspaceDirectory;
export const hostedNotebookPath = resolve(hostedWorkspaceDirectory, "notebook.py");
export const mainPlaywrightOutputDirectory = mutable.mainPlaywrightOutputDirectory;
export const providerPlaywrightOutputDirectory = mutable.providerPlaywrightOutputDirectory;
export const mainPlaywrightReportDirectory = mutable.mainPlaywrightReportDirectory;
export const providerPlaywrightReportDirectory = mutable.providerPlaywrightReportDirectory;
