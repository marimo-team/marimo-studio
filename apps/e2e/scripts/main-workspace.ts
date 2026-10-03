import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { copyFixtureProviderPackage } from "./fixture-provider-package.ts";
import { e2eNetwork } from "./network.ts";
import { NotebookServices } from "./notebook-services.ts";
import {
  appDirectory,
  configDirectory,
  fixtureDirectory,
  hostedFixtureDirectory,
  hostedNotebookPath,
  hostedWorkspaceDirectory,
  lazyNotebookPath,
  proxiedDirectoryNotebookPath,
  proxiedDirectoryWorkspaceDirectory,
  proxiedFixtureDirectory,
  proxiedNotebookPath,
  proxiedRunNotebookPath,
  proxiedRunWorkspaceDirectory,
  proxiedWorkspaceDirectory,
  repositoryDirectory,
  staticExportDirectory,
  workspaceDirectory,
} from "./paths.ts";
import { PreparationProcessOwner } from "./preparation-process.ts";

const workspaceDirectories = [
  configDirectory,
  workspaceDirectory,
  hostedWorkspaceDirectory,
  proxiedWorkspaceDirectory,
  proxiedRunWorkspaceDirectory,
  proxiedDirectoryWorkspaceDirectory,
];

/** The proxied run server authenticates browsers with this access token. */
export const PROXIED_RUN_TOKEN = "studio-proxied-token";

export class MainWorkspace {
  #preparation = new PreparationProcessOwner();
  #services = new NotebookServices(configDirectory);

  async prepare() {
    await this.#services.prepare();
    for (const path of workspaceDirectories) {
      await rm(path, { force: true, recursive: true });
      await mkdir(path, { recursive: true });
    }
    await cp(fixtureDirectory, workspaceDirectory, { recursive: true });
    await copyFixtureProviderPackage(workspaceDirectory);
  }

  async start(services: readonly string[]) {
    for (const service of services) {
      if (service === "studio") await this.#studio();
      else if (service === "hosted") await this.#hosted();
      else if (service === "static") await this.#static();
      else if (service === "proxied") await this.#proxied();
      else if (service === "proxiedRun") await this.#proxiedRun();
      else if (service === "proxiedDirectory") await this.#proxiedDirectory();
      else throw new TypeError(`Unknown browser service ${service}`);
    }
  }

  #studio() {
    const endpoint = e2eNetwork.main.studio;
    return this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/server.py"),
        "marimo",
        "edit",
        workspaceDirectory,
        "--no-sandbox",
        "--headless",
        "--no-token",
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
        resolve(appDirectory, "scripts/_compat/server.py"),
        "marimo",
        "edit",
        hostedNotebookPath,
        "--no-sandbox",
        "--headless",
        "--token-password",
        "studio-e2e-token",
        "--base-url",
        "/hosted",
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

  // A path-prefixing proxy strips its mount before forwarding, so marimo runs
  // without --base-url and never sees the public path.
  async #proxied() {
    await cp(resolve(proxiedFixtureDirectory, "notebook.py"), proxiedNotebookPath);
    const endpoint = e2eNetwork.main.proxied;
    await this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/server.py"),
        "marimo",
        "edit",
        proxiedNotebookPath,
        "--no-sandbox",
        "--headless",
        "--no-token",
      ],
      endpoint,
      "studio",
      { serverUrl: endpoint.publicUrl, readyUrl: `${endpoint.publicUrl}/` },
    );
  }

  async #proxiedRun() {
    await this.#prepareProxiedViews(proxiedRunNotebookPath);
    const endpoint = e2eNetwork.main.proxiedRun;
    await this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/server.py"),
        "marimo",
        "run",
        proxiedRunNotebookPath,
        "--no-sandbox",
        "--headless",
        "--token-password",
        PROXIED_RUN_TOKEN,
      ],
      endpoint,
      "process",
      {
        serverUrl: endpoint.publicUrl,
        readyUrl: `${endpoint.publicUrl}/?access_token=${PROXIED_RUN_TOKEN}`,
        authToken: PROXIED_RUN_TOKEN,
      },
    );
  }

  // A directory server routes each notebook through its `file` query. It uses
  // marimo's server-sent event transport, so proxied tests cover both kernel
  // transports beneath a prefix.
  async #proxiedDirectory() {
    await this.#prepareProxiedViews(proxiedDirectoryNotebookPath);
    const endpoint = e2eNetwork.main.proxiedDirectory;
    await this.#services.start(
      [
        "python",
        resolve(appDirectory, "scripts/_compat/server.py"),
        "marimo",
        "edit",
        dirname(proxiedDirectoryNotebookPath),
        "--no-sandbox",
        "--headless",
        "--no-token",
      ],
      endpoint,
      "studio",
      {
        environment: { MARIMO_SERVER_TRANSPORT: "sse" },
        serverUrl: endpoint.publicUrl,
        readyUrl: `${endpoint.publicUrl}/?file=notebook.py`,
      },
    );
  }

  async #prepareProxiedViews(notebook: string) {
    await cp(resolve(proxiedFixtureDirectory, "notebook.py"), notebook);
    for (const view of ["dashboard", "report"]) {
      await this.#preparation.run(
        `proxied ${view} view`,
        "uv",
        [
          "run",
          "--frozen",
          "--group",
          "e2e",
          "marimo-studio",
          "view",
          "create",
          view,
          "--target",
          notebook,
          "--starter",
          "marimo-studio/vanilla:default",
        ],
        {
          cwd: repositoryDirectory,
          env: { ...process.env, PYTHONUNBUFFERED: "1" },
          stdio: ["ignore", "ignore", "inherit"],
        },
      );
      const viewDirectory = resolve(dirname(notebook), "__marimo__/studio/notebook", view);
      await writeFile(
        resolve(viewDirectory, "index.html"),
        await readFile(resolve(proxiedFixtureDirectory, `${view}.html`)),
      );
      if (view === "report") {
        await cp(resolve(proxiedFixtureDirectory, "view.css"), resolve(viewDirectory, "view.css"));
      }
    }
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
        resolve(repositoryDirectory, "apps/e2e/scripts/static-server.py"),
        "0",
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
      workspaceDirectories.map((path) =>
        rm(path, { force: true, recursive: true, maxRetries: 20, retryDelay: 50 }),
      ),
    );
  }
}
