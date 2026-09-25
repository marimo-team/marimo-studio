import { resolve } from "node:path";

import type { E2EEndpoint } from "../scripts/network.ts";

import {
  configDirectory,
  notebookProcessRegistryDirectory,
  repositoryDirectory,
} from "../scripts/paths.ts";
import { ServerHandle } from "../scripts/server-process.ts";

interface NotebookServerOptions {
  command: "edit" | "run";
  target: string;
  endpoint: E2EEndpoint;
  authentication: readonly string[];
  editRoot?: "marimo" | "studio";
  environment?: NodeJS.ProcessEnv;
  extensions?: "native" | "studio";
  registryDirectory?: string;
  sandbox?: boolean;
}

interface NotebookServerTimeoutOptions {
  readonly timeout?: number;
}

export const startNotebookServer = ({
  command,
  target,
  endpoint,
  authentication,
  editRoot = "studio",
  environment: extraEnvironment = {},
  extensions = "studio",
  registryDirectory = notebookProcessRegistryDirectory,
  sandbox = false,
}: NotebookServerOptions): ServerHandle => {
  const environment: NodeJS.ProcessEnv = {
    ...process.env,
    ...extraEnvironment,
    PYTHONUNBUFFERED: "1",
    XDG_CONFIG_HOME: configDirectory,
  };
  delete environment.MARIMO_KERNEL_LIFESPAN_ALLOWLIST;
  delete environment.MARIMO_KERNEL_LIFESPAN_DENYLIST;
  delete environment.MARIMO_SERVER_ASGI_MIDDLEWARE_ALLOWLIST;
  delete environment.MARIMO_SERVER_ASGI_MIDDLEWARE_DENYLIST;
  environment.MARIMO_STUDIO_EDIT_ROOT = editRoot;
  if (extensions === "native") {
    environment.MARIMO_KERNEL_LIFESPAN_DENYLIST = "marimo-studio";
    environment.MARIMO_SERVER_ASGI_MIDDLEWARE_DENYLIST = "marimo-studio";
  }
  const passwordOption = authentication.indexOf("--token-password");
  return new ServerHandle({
    authToken: passwordOption >= 0 ? authentication[passwordOption + 1] : undefined,
    studioEntry: editRoot === "marimo" ? "/studio" : "",
    shutdown: command === "run" ? "process" : "studio",
    endpoint,
    command: "uv",
    args: [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "python",
      resolve(repositoryDirectory, "apps/e2e/scripts/_compat/server.py"),
      "marimo",
      command,
      target,
      sandbox ? "--sandbox" : "--no-sandbox",
      "--headless",
      ...authentication,
    ],
    cwd: repositoryDirectory,
    directory: registryDirectory,
    env: environment,
  });
};

export interface NotebookServerCleanupFailure {
  message: string;
}

export const closeFailedNotebookServer = async (
  server: ServerHandle,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<NotebookServerCleanupFailure | undefined> => {
  try {
    await server.close({ timeout });
    return undefined;
  } catch (error) {
    return {
      message:
        error instanceof Error
          ? (error.stack ?? error.message)
          : "Notebook server cleanup failed with a non-error value.",
    };
  }
};
