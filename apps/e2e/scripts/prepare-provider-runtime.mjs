import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

import {
  externalProviderNotebookFixture,
  externalProviderNotebookPath,
  providerNotebookFixturePath,
  providerNotebookPath,
  providerStaticRoot,
  providerWorkspaceDirectory,
} from "./paths.mjs";

const targetViews = resolve(providerWorkspaceDirectory, "__marimo__/studio/projections");
const removeTree = (directory) =>
  rm(directory, {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 100,
  });

export const clearProviderGeneratedState = async () => {
  for (const view of ["overview", "gallery", "story", "web", "slides"]) {
    await removeTree(resolve(targetViews, view, ".artifacts"));
  }
  await removeTree(resolve(targetViews, ".locks"));
};

export const prepareProviderWorkspace = async () => {
  await removeTree(providerWorkspaceDirectory);
  await removeTree(providerStaticRoot);
  await mkdir(providerWorkspaceDirectory, { recursive: true });
  await mkdir(providerStaticRoot, { recursive: true });
  await cp(providerNotebookFixturePath, providerNotebookPath);
  await cp(externalProviderNotebookFixture, externalProviderNotebookPath);
};

export const cleanProviderWorkspace = () =>
  Promise.all(
    [providerWorkspaceDirectory, providerStaticRoot].map((directory) => removeTree(directory)),
  );
