import { rm } from "node:fs/promises";

import type { E2EEndpoint } from "./network.ts";

import {
  closeNotebookProcessRegistry,
  stopRegisteredNotebookProcesses,
} from "./notebook-process-registry.ts";
import { notebookProcessRegistryDirectory, repositoryDirectory } from "./paths.ts";
import { ServerHandle, type ProcessOutput } from "./server-process.ts";

interface ServicesOptions {
  registryDirectory?: string;
  command?: string;
  prefix?: string[];
  cwd?: string;
  environment?: NodeJS.ProcessEnv;
  forward?: ProcessOutput;
}
interface StartOptions {
  environment?: NodeJS.ProcessEnv;
  serverUrl?: string;
  readyUrl?: string;
  authToken?: string;
  studioEntry?: string;
  timeout?: number;
}

export class NotebookServices {
  readonly #servers: ServerHandle[] = [];
  readonly #configDirectory: string;
  readonly #options: ServicesOptions;
  #closing: Promise<void> | undefined;

  constructor(configDirectory: string, options: ServicesOptions = {}) {
    this.#configDirectory = configDirectory;
    this.#options = options;
  }

  get #registry() {
    return { directory: this.#options.registryDirectory ?? notebookProcessRegistryDirectory };
  }

  async prepare() {
    if (this.#closing) throw new Error("Browser services are closing");
    closeNotebookProcessRegistry(this.#registry);
    await stopRegisteredNotebookProcesses({ ...this.#registry, signal: "SIGKILL" });
    await rm(this.#registry.directory, { force: true, recursive: true });
  }

  async start(
    args: string[],
    endpoint: E2EEndpoint,
    shutdown: "studio" | "process",
    options: StartOptions = {},
  ): Promise<ServerHandle> {
    if (this.#closing) throw new Error("Browser services are closing");
    const server = new ServerHandle({
      ...options,
      endpoint,
      shutdown,
      command: this.#options.command ?? "uv",
      args: [...(this.#options.prefix ?? ["run", "--frozen", "--group", "e2e"]), ...args],
      cwd: this.#options.cwd ?? repositoryDirectory,
      directory: this.#registry.directory,
      forward: this.#options.forward,
      env: {
        ...(this.#options.environment ?? process.env),
        ...options.environment,
        PYTHONUNBUFFERED: "1",
        XDG_CONFIG_HOME: this.#configDirectory,
      },
    });
    this.#servers.push(server);
    await server.waitUntilReady(options.readyUrl, { timeout: options.timeout });
    return server;
  }

  async waitForExit(): Promise<never> {
    throw await Promise.race(this.#servers.map((server) => server.exited));
  }

  close() {
    this.#closing ??= this.#close();
    return this.#closing;
  }

  async #close() {
    closeNotebookProcessRegistry(this.#registry);
    const results = await Promise.allSettled(
      this.#servers.map((server) => server.close({ timeout: 10_000 })),
    );
    const errors: unknown[] = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    try {
      await stopRegisteredNotebookProcesses({ ...this.#registry, signal: "SIGKILL" });
    } catch (error) {
      errors.push(error);
    }
    if (errors.length) throw new AggregateError(errors, "Browser services shutdown failed");
  }
}
