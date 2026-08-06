import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const directory = dirname(fileURLToPath(import.meta.url));

export const appDirectory = resolve(directory, "..");
export const repositoryDirectory = resolve(appDirectory, "../..");
export const configDirectory = resolve(appDirectory, "test-results/xdg-config");
export const fixtureDirectory = resolve(appDirectory, "fixtures");
export const workspaceDirectory = resolve(appDirectory, ".workspace");
export const notebookPath = resolve(workspaceDirectory, "notebook.py");
export const hostedFixtureDirectory = resolve(appDirectory, "fixtures-hosted");
export const hostedWorkspaceDirectory = resolve(appDirectory, "test-results/workspaces/hosted");
export const hostedNotebookPath = resolve(hostedWorkspaceDirectory, "notebook.py");
