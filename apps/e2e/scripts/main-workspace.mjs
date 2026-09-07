import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

import { copyFixtureProviderPackage } from "./fixture-provider-package.mjs";
import { e2eNetwork } from "./network.mjs";
import { NotebookServices } from "./notebook-services.mjs";
import {
  appDirectory,
  configDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  lazyNotebookPath,
  repositoryDirectory,
  staticExportDirectory,
  workspaceDirectory,
} from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";

export class MainWorkspace {
  #preparation = new PreparationProcessOwner();
  #services = new NotebookServices(configDirectory);

  async prepare() {
    await this.#services.prepare();
    for (const path of [configDirectory, workspaceDirectory, hostedWorkspaceDirectory]) {
      await rm(path, { force: true, recursive: true });
      await mkdir(path, { recursive: true });
    }
    await cp(fixtureDirectory, workspaceDirectory, { recursive: true });
    await copyFixtureProviderPackage(workspaceDirectory);
  }

  async start(services) {
    for (const service of services) {
      if (service === "studio") await this.#studio();
      else if (service === "hosted") await this.#hosted();
      else if (service === "static") await this.#static();
      else throw new TypeError(`Unknown browser service ${service}`);
    }
  }

  #studio() {
    const endpoint = e2eNetwork.main.studio;
    return this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/marimo_edit.py"),
        "--port-offset",
        String(e2eNetwork.portOffset),
        workspaceDirectory,
        "--no-sandbox",
        "--headless",
        "--no-token",
        "--host",
        "127.0.0.1",
        "--port",
        String(endpoint.port),
      ],
      endpoint,
      "studio",
      {
        environment: {
          MARIMO_STUDIO_ALLOWED_EMBED_ORIGINS: `http://localhost:${e2eNetwork.main.exported.port}`,
        },
      },
    );
  }

  async #hosted() {
    await cp(hostedFixtureDirectory, hostedWorkspaceDirectory, { recursive: true });
    const endpoint = e2eNetwork.main.hosted;
    await this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/marimo_edit.py"),
        "--port-offset",
        String(e2eNetwork.portOffset),
        hostedNotebookPath,
        "--no-sandbox",
        "--headless",
        "--token-password",
        "studio-e2e-token",
        "--base-url",
        "/hosted",
        "--host",
        "127.0.0.1",
        "--port",
        String(endpoint.port),
      ],
      endpoint,
      "studio",
      {
        environment: { MARIMO_STUDIO_EDIT_ROOT: "marimo" },
        serverUrl: `${endpoint.origin}/hosted`,
        readyUrl: `${endpoint.origin}/hosted/?access_token=studio-e2e-token`,
        authToken: "studio-e2e-token",
        studioEntry: "/studio",
      },
    );
  }

  async #static() {
    await this.#preparation.run(
      "static fixture export",
      "uv",
      [
        "run",
        "--frozen",
        "--group",
        "e2e",
        "marimo-studio",
        "view",
        "export",
        "dashboard",
        "--target",
        lazyNotebookPath,
        "--output",
        staticExportDirectory,
        "--runtime",
        "wasm",
      ],
      {
        cwd: repositoryDirectory,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        stdio: "inherit",
      },
    );
    await cp(
      resolve(fixtureDirectory, "embed-host.html"),
      resolve(staticExportDirectory, "embed-host.html"),
    );
    const endpoint = e2eNetwork.main.exported;
    await this.#services.start(
      [
        "python",
        "-m",
        "http.server",
        String(endpoint.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        staticExportDirectory,
      ],
      endpoint,
      "process",
      { readyUrl: `${endpoint.origin}/src/index.html` },
    );
  }

  async close() {
    const results = await Promise.allSettled([this.#preparation.stop(), this.#services.close()]);
    const errors = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    if (errors.length > 0) throw new AggregateError(errors, "Browser workspace shutdown failed");
    await Promise.all(
      [configDirectory, workspaceDirectory, hostedWorkspaceDirectory].map((path) =>
        rm(path, { force: true, recursive: true, maxRetries: 20, retryDelay: 50 }),
      ),
    );
  }
}
