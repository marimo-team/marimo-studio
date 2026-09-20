import type { ChildProcess } from "node:child_process";

import { connect } from "node:net";
import { resolve } from "node:path";

import type { e2eNetwork } from "../scripts/network.mjs";

import { unregisterNotebookProcess } from "../scripts/notebook-process-registry.mjs";
import {
  configDirectory,
  notebookProcessRegistryDirectory,
  repositoryDirectory,
} from "../scripts/paths.mjs";
import { processGroupIsRunning, stopProcessGroup } from "../scripts/process-group.mjs";
import { startRoutedNotebookProcess } from "../scripts/routed-notebook-process.mjs";
import { stopNotebookProcess, waitForServer } from "../scripts/server-process.mjs";

interface NotebookServerOptions {
  command: "edit" | "run";
  target: string;
  endpoint: typeof e2eNetwork.main.studio;
  authentication: readonly string[];
  editRoot?: "marimo" | "studio";
  environment?: NodeJS.ProcessEnv;
  extensions?: "native" | "studio";
  registryDirectory?: string;
}

interface NotebookServerTimeoutOptions {
  readonly timeout?: number;
}

const notebookRegistrations = new WeakMap<
  ChildProcess,
  { directory: string; ownerNonce: string; processGroupId: number }
>();

export interface NotebookServer {
  process: ChildProcess;
  processGroupId: number | undefined;
  port: number | null;
  beginClose(): void;
  releaseRoute(): void;
  ready: Promise<void>;
  serverUrl: string;
  studioEntry?: string;
  shutdown: "run" | "studio";
  authToken: string | undefined;
  output(): string;
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
}: NotebookServerOptions): NotebookServer => {
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
  const registration = startRoutedNotebookProcess({
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
      "--no-sandbox",
      "--headless",
      ...authentication,
    ],
    cwd: repositoryDirectory,
    directory: registryDirectory,
    env: environment,
  });
  const { child, ownerNonce, processGroupId } = registration;
  const output = registration.output;
  const ready = registration.ready;
  if (processGroupId !== undefined) {
    notebookRegistrations.set(child, {
      directory: registryDirectory,
      ownerNonce,
      processGroupId,
    });
  }
  const passwordOption = authentication.indexOf("--token-password");
  return {
    authToken: passwordOption >= 0 ? authentication[passwordOption + 1] : undefined,
    output,
    get port() {
      return registration.port;
    },
    beginClose: registration.beginClose,
    releaseRoute: registration.releaseRoute,
    process: child,
    processGroupId,
    ready,
    serverUrl: endpoint.origin,
    studioEntry: editRoot === "marimo" ? "/studio" : "",
    shutdown: command === "run" ? "run" : "studio",
  };
};

export const waitForNotebookServer = async (
  server: NotebookServer,
  url: string,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<void> => {
  await server.ready.catch((error) => {
    throw new Error(`Notebook process registration failed: ${String(error)}\n${server.output()}`);
  });
  await waitForServer(server.process, url, { output: server.output, timeout });
};

export const stopNotebookServer = async (
  server: NotebookServer,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<void> => {
  server.beginClose();
  try {
    await stopNotebookProcess(
      {
        authToken: server.authToken ?? "",
        child: server.process,
        output: server.output,
        port: server.port,
        processGroupId: server.processGroupId,
        serverUrl: server.serverUrl,
        studioEntry: server.studioEntry,
        beginClose: server.beginClose,
        releaseRoute: server.releaseRoute,
      },
      { shutdown: server.shutdown, timeout },
    );
  } finally {
    if (
      server.processGroupId !== undefined &&
      (processGroupIsRunning(server.processGroupId) ??
        (server.process.exitCode === null && server.process.signalCode === null)) === false
    ) {
      const registration = notebookRegistrations.get(server.process);
      if (registration) {
        unregisterNotebookProcess(registration, { directory: registration.directory });
      }
    }
  }
};

export const notebookServerPortIsOpen = (port: number | null): Promise<boolean> =>
  port === null
    ? Promise.resolve(false)
    : new Promise((resolveOpen) => {
        const socket = connect({ host: "127.0.0.1", port });
        const finish = (open: boolean) => {
          socket.destroy();
          resolveOpen(open);
        };
        socket.setTimeout(100, () => finish(false));
        socket.once("connect", () => finish(true));
        socket.once("error", () => finish(false));
      });

export interface NotebookServerCleanupFailure {
  message: string;
}

export const closeFailedNotebookServer = async (
  server: NotebookServer,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<NotebookServerCleanupFailure | undefined> => {
  let firstFailure: NotebookServerCleanupFailure | undefined;
  try {
    await stopNotebookServer(server, { timeout });
    return undefined;
  } catch (error) {
    firstFailure = {
      message:
        error instanceof Error
          ? (error.stack ?? error.message)
          : "Notebook server cleanup failed with a non-error value.",
    };
  }
  const groupRunning =
    server.processGroupId === undefined
      ? server.process.exitCode === null && server.process.signalCode === null
      : (processGroupIsRunning(server.processGroupId) ?? true);
  if (!groupRunning && !(await notebookServerPortIsOpen(server.port))) return firstFailure;
  if (server.processGroupId !== undefined && groupRunning) {
    stopProcessGroup(server.processGroupId, "SIGKILL");
  }
  try {
    await stopNotebookServer(server, { timeout });
  } catch {
    // The first shutdown diagnostic remains authoritative for this cleanup attempt.
  }
  return firstFailure;
};
