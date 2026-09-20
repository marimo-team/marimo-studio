import { cp, mkdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

import type { E2EEndpoint } from "./network.ts";

import { copyFixtureProviderPackage } from "./fixture-provider-package.ts";
import { e2eNetwork } from "./network.ts";
import { NotebookServices } from "./notebook-services.ts";
import {
  externalProviderNotebookPath,
  externalProviderNotebookFixture,
  providerNotebookFixturePath,
  providerStaticRoot,
  providerConfigDirectory,
  providerGalleryStaticDirectory,
  providerNotebookPath,
  providerNotebookStaticDirectory,
  providerNotebookPreparedDirectory,
  providerRevealStaticDirectory,
  providerStoryStaticDirectory,
  providerWebStaticDirectory,
  providerWorkspaceDirectory,
  repositoryDirectory,
} from "./paths.ts";
import { PreparationProcessOwner } from "./preparation-process.ts";
const removeTree = (directory: string) =>
  rm(directory, { force: true, recursive: true, maxRetries: 10, retryDelay: 100 });

interface Candidate {
  view: string;
  starter: string;
  files?: Record<string, string>;
  exports?: { directory: string; endpoint: E2EEndpoint; runtime: string; entrypoint?: string }[];
}

const candidates: Candidate[] = [
  { view: "overview", starter: "marimo-studio/vanilla:default" },
  {
    view: "notebook",
    starter: "marimo-studio/notebook-kit:default",
    files: {
      "src/index.html": resolve(repositoryDirectory, "apps/e2e/fixtures-provider/notebook.html"),
      "src/rows.json": resolve(repositoryDirectory, "apps/e2e/fixtures-provider/rows.json"),
      "states.yaml": resolve(
        repositoryDirectory,
        "apps/e2e/fixtures-provider/notebook-states.yaml",
      ),
    },
    exports: [
      {
        directory: providerNotebookStaticDirectory,
        endpoint: e2eNetwork.provider.notebook,
        runtime: "wasm",
      },
      {
        directory: providerNotebookPreparedDirectory,
        endpoint: e2eNetwork.provider.notebookPrepared,
        runtime: "zero-python",
      },
    ],
  },
  {
    view: "gallery",
    starter: "marimo-studio/react:default",
    exports: [
      {
        directory: providerGalleryStaticDirectory,
        endpoint: e2eNetwork.provider.gallery,
        runtime: "wasm",
      },
    ],
  },
  {
    view: "story",
    starter: "marimo-studio/svelte:default",
    exports: [
      {
        directory: providerStoryStaticDirectory,
        endpoint: e2eNetwork.provider.story,
        runtime: "wasm",
      },
    ],
  },
  {
    view: "slides",
    starter: "marimo-studio/react:reveal",
    exports: [
      {
        directory: providerRevealStaticDirectory,
        endpoint: e2eNetwork.provider.reveal,
        runtime: "wasm",
      },
    ],
  },
  {
    view: "web",
    starter: "marimo-studio-e2e-provider/web:default",
    exports: [
      {
        directory: providerWebStaticDirectory,
        endpoint: e2eNetwork.provider.web,
        runtime: "wasm",
        entrypoint: "src/index.html",
      },
    ],
  },
  { view: "dashboard", starter: "marimo-studio-e2e-provider/report:default" },
];

export class ProviderWorkspace {
  #preparation = new PreparationProcessOwner();
  #services = new NotebookServices(providerConfigDirectory);

  async prepare(views: readonly string[]) {
    await this.#services.prepare();
    for (const directory of [
      providerWorkspaceDirectory,
      providerStaticRoot,
      providerConfigDirectory,
    ]) {
      await removeTree(directory);
      await mkdir(directory, { recursive: true });
    }
    await cp(providerNotebookFixturePath, providerNotebookPath);
    await cp(externalProviderNotebookFixture, externalProviderNotebookPath);
    await copyFixtureProviderPackage(providerWorkspaceDirectory);
    const selected = candidates.filter(({ view }) => view === "overview" || views.includes(view));
    for (const candidate of selected) {
      const notebook =
        candidate.view === "dashboard" ? externalProviderNotebookPath : providerNotebookPath;
      await this.#run(`create ${candidate.view}`, [
        "view",
        "create",
        candidate.view,
        "--target",
        notebook,
        "--starter",
        candidate.starter,
        "--json",
      ]);
      for (const [relative, source] of Object.entries(candidate.files ?? {})) {
        await cp(
          source,
          resolve(
            providerWorkspaceDirectory,
            "__marimo__/studio/projections",
            candidate.view,
            relative,
          ),
        );
      }
      for (const publication of candidate.exports ?? []) {
        await this.#run(`export ${candidate.view}`, [
          "view",
          "export",
          candidate.view,
          "--target",
          notebook,
          "--output",
          publication.directory,
          "--runtime",
          publication.runtime,
          "--json",
        ]);
      }
    }
    const projections = resolve(providerWorkspaceDirectory, "__marimo__/studio/projections");
    for (const candidate of selected) {
      await removeTree(resolve(projections, candidate.view, ".artifacts"));
    }
    await removeTree(resolve(projections, ".locks"));
    for (const candidate of selected) {
      for (const publication of candidate.exports ?? []) {
        await this.#services.start(
          [
            "python",
            resolve(repositoryDirectory, "apps/e2e/scripts/static-server.py"),
            "0",
            "--bind",
            "127.0.0.1",
            "--directory",
            publication.directory,
          ],
          publication.endpoint,
          "process",
          {
            readyUrl: `${publication.endpoint.origin}/${publication.entrypoint ?? "index.html"}`,
          },
        );
      }
    }
    if (views.includes("dashboard")) {
      await this.#runServer(externalProviderNotebookPath, e2eNetwork.provider.external);
    }
    if (views.some((view) => view !== "dashboard" && view !== "slides")) {
      await this.#runServer(providerNotebookPath, e2eNetwork.provider.live);
    }
  }

  #run(label: string, args: string[]) {
    return this.#preparation.run(
      label,
      "uv",
      ["run", "--frozen", "--group", "e2e", "marimo-studio", ...args],
      {
        cwd: repositoryDirectory,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        stdio: "inherit",
      },
    );
  }

  #runServer(notebook: string, endpoint: E2EEndpoint) {
    return this.#services.start(
      [
        "python",
        resolve(repositoryDirectory, "apps/e2e/scripts/_compat/server.py"),
        "marimo",
        "run",
        notebook,
        "--no-sandbox",
        "--headless",
        "--no-token",
      ],
      endpoint,
      "process",
      { readyUrl: `${endpoint.origin}/_marimo-studio/status` },
    );
  }

  async close() {
    const results = await Promise.allSettled([this.#preparation.stop(), this.#services.close()]);
    const errors = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    if (errors.length > 0) throw new AggregateError(errors, "Provider workspace shutdown failed");
    await Promise.all(
      [providerWorkspaceDirectory, providerStaticRoot, providerConfigDirectory].map(removeTree),
    );
  }
}
