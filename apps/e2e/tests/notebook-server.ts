import type { ChildProcess } from "node:child_process";
import type { AddressInfo } from "node:net";

import { connect, createServer } from "node:net";

import { unregisterNotebookProcess } from "../scripts/notebook-process-registry.mjs";
import {
  configDirectory,
  notebookProcessRegistryDirectory,
  repositoryDirectory,
} from "../scripts/paths.mjs";
import { processGroupIsRunning, stopProcessGroup } from "../scripts/process-group.mjs";
import { startRegisteredNotebookProcess } from "../scripts/registered-notebook-process.mjs";
import {
  captureProcessOutput,
  stopNotebookProcess,
  waitForServer,
} from "../scripts/server-process.mjs";

interface NotebookServerOptions {
  command: "edit" | "run";
  target: string;
  port: number;
  authentication: readonly string[];
  editRoot?: "marimo" | "studio";
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
  port: number;
  ready: Promise<void>;
  serverUrl: string;
  studioEntry?: string;
  shutdown: "run" | "studio";
  authToken: string | undefined;
  output(): string;
}

export const availablePort = async (): Promise<number> => {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  // SAFETY: Listening with a TCP host and port makes Node return AddressInfo.
  const address = server.address() as AddressInfo | null;
  if (address === null) {
    throw new Error("TCP listener did not expose its assigned port");
  }
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error === undefined ? resolveClose() : reject(error)));
  });
  return address.port;
};

export const startNotebookServer = ({
  command,
  target,
  port,
  authentication,
  editRoot = "studio",
  extensions = "studio",
  registryDirectory = notebookProcessRegistryDirectory,
}: NotebookServerOptions): NotebookServer => {
  const environment: NodeJS.ProcessEnv = {
    ...process.env,
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
  const registration = startRegisteredNotebookProcess({
    command: "uv",
    args: [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo",
      command,
      target,
      "--no-sandbox",
      "--headless",
      ...authentication,
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: repositoryDirectory,
    directory: registryDirectory,
    env: environment,
    port,
  });
  const { child, ownerNonce, processGroupId } = registration;
  const output = captureProcessOutput(child);
  const ready = registration.ready.catch((error) => {
    throw new Error(`Notebook process registration failed: ${String(error)}\n${output()}`);
  });
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
    port,
    process: child,
    processGroupId,
    ready,
    serverUrl: `http://127.0.0.1:${port}`,
    studioEntry: editRoot === "marimo" ? "/studio" : "",
    shutdown: command === "run" ? "run" : "studio",
  };
};

export const waitForNotebookServer = async (
  server: NotebookServer,
  url: string,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<void> => {
  await server.ready;
  await waitForServer(server.process, url, { output: server.output, timeout });
};

export const stopNotebookServer = async (
  server: NotebookServer,
  { timeout }: NotebookServerTimeoutOptions = {},
): Promise<void> => {
  await server.ready.catch(() => undefined);
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

export const notebookServerPortIsOpen = (port: number): Promise<boolean> =>
  new Promise((resolveOpen) => {
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
