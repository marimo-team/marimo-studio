import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const directory = dirname(fileURLToPath(import.meta.url));

export const appDirectory = resolve(directory, "..");
export const repositoryDirectory = resolve(appDirectory, "../..");
export const fixtureDirectory = resolve(appDirectory, "fixtures");
export const workspaceDirectory = resolve(appDirectory, ".workspace");
export const notebookPath = resolve(workspaceDirectory, "notebook.py");
