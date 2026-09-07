import { rm } from "node:fs/promises";

import {
  closeNotebookProcessRegistry,
  stopRegisteredNotebookProcesses,
} from "./notebook-process-registry.mjs";
import { notebookProcessRegistryDirectory, repositoryDirectory } from "./paths.mjs";
import { startRegisteredNotebookProcess } from "./registered-notebook-process.mjs";
import { observeServerExit } from "./server-exit.mjs";
import { captureProcessOutput, stopNotebookProcess, waitForServer } from "./server-process.mjs";

export class NotebookServices {
  #servers = [];
  #closing;

  constructor(configDirectory) {
    this.configDirectory = configDirectory;
  }

  async prepare() {
    if (this.#closing !== undefined) throw new Error("Browser services are closing");
    closeNotebookProcessRegistry();
    await stopRegisteredNotebookProcesses({ signal: "SIGKILL" });
    await rm(notebookProcessRegistryDirectory, { force: true, recursive: true });
  }
  async start(args, endpoint, shutdown, options = {}) {
    if (this.#closing !== undefined) throw new Error("Browser services are closing");
    const registration = startRegisteredNotebookProcess({
      command: "uv",
      args: ["run", "--frozen", "--group", "e2e", ...args],
      cwd: repositoryDirectory,
      directory: notebookProcessRegistryDirectory,
      port: endpoint.port,
      env: {
        ...process.env,
        ...options.environment,
        PYTHONUNBUFFERED: "1",
        XDG_CONFIG_HOME: this.configDirectory,
      },
    });
    const output = captureProcessOutput(registration.child);
    const server = {
      child: registration.child,
      processGroupId: registration.processGroupId,
      output,
      port: endpoint.port,
      serverUrl: options.serverUrl ?? endpoint.origin,
      authToken: options.authToken,
      studioEntry: options.studioEntry,
      shutdown,
      exit: observeServerExit(registration.child, output),
    };
    this.#servers.push(server);
    await registration.ready;
    await waitForServer(server.child, options.readyUrl ?? server.serverUrl, { output });
  }

  close() {
    this.#closing ??= this.#close();
    return this.#closing;
  }

  async #close() {
    closeNotebookProcessRegistry();
    const errors = [];
    for (const { exit } of this.#servers) {
      const failure = exit.shutdown();
      if (failure !== undefined) errors.push(failure);
    }
    const results = await Promise.allSettled(
      this.#servers.map(({ shutdown, exit: _exit, ...server }) =>
        stopNotebookProcess(server, { shutdown, timeout: 10_000 }),
      ),
    );
    errors.push(
      ...results.filter((result) => result.status === "rejected").map((result) => result.reason),
    );
    try {
      await stopRegisteredNotebookProcesses({ signal: "SIGKILL" });
    } catch (error) {
      errors.push(error);
    }
    if (errors.length > 0) throw new AggregateError(errors, "Browser services shutdown failed");
  }
}
