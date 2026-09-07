import { mkdir, rm } from "node:fs/promises";

import { cleanupProviderEnvironment } from "./cleanup-provider-runtime.mjs";
import { copyFixtureProviderPackage } from "./fixture-provider-package.mjs";
import { e2eNetwork } from "./network.mjs";
import { NotebookServices } from "./notebook-services.mjs";
import {
  externalProviderNotebookPath,
  providerConfigDirectory,
  providerGalleryStaticDirectory,
  providerNotebookPath,
  providerRevealStaticDirectory,
  providerStoryStaticDirectory,
  providerWebStaticDirectory,
  providerWorkspaceDirectory,
  repositoryDirectory,
} from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import {
  clearProviderGeneratedState,
  prepareProviderWorkspace,
} from "./prepare-provider-runtime.mjs";

const candidates = [
  { view: "overview", starter: "marimo-studio/vanilla:default" },
  {
    view: "gallery",
    starter: "marimo-studio/react:default",
    output: providerGalleryStaticDirectory,
    endpoint: e2eNetwork.provider.gallery,
  },
  {
    view: "story",
    starter: "marimo-studio/svelte:default",
    output: providerStoryStaticDirectory,
    endpoint: e2eNetwork.provider.story,
  },
  {
    view: "slides",
    starter: "marimo-studio/react:reveal",
    output: providerRevealStaticDirectory,
    endpoint: e2eNetwork.provider.reveal,
  },
  {
    view: "web",
    starter: "marimo-studio-e2e-provider/web:default",
    output: providerWebStaticDirectory,
    endpoint: e2eNetwork.provider.web,
  },
  { view: "dashboard", starter: "marimo-studio-e2e-provider/report:default" },
];

export class ProviderWorkspace {
  #preparation = new PreparationProcessOwner();
  #services = new NotebookServices(providerConfigDirectory);

  async prepare(views) {
    await this.#services.prepare();
    await prepareProviderWorkspace();
    await copyFixtureProviderPackage(providerWorkspaceDirectory);
    await rm(providerConfigDirectory, { force: true, recursive: true });
    await mkdir(providerConfigDirectory, { recursive: true });
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
      if (candidate.output !== undefined) {
        await this.#run(`export ${candidate.view}`, [
          "view",
          "export",
          candidate.view,
          "--target",
          notebook,
          "--output",
          candidate.output,
          "--runtime",
          "wasm",
          "--json",
        ]);
      }
    }
    await clearProviderGeneratedState();
    for (const candidate of selected) {
      if (candidate.output === undefined) continue;
      await this.#services.start(
        [
          "python",
          "-m",
          "http.server",
          String(candidate.endpoint.port),
          "--bind",
          "127.0.0.1",
          "--directory",
          candidate.output,
        ],
        candidate.endpoint,
        "process",
        {
          readyUrl: `${candidate.endpoint.origin}/${candidate.view === "web" ? "src/index.html" : ""}`,
        },
      );
    }
    if (views.includes("dashboard")) {
      await this.#runServer(externalProviderNotebookPath, e2eNetwork.provider.external);
    }
    if (views.some((view) => view !== "dashboard" && view !== "slides")) {
      await this.#runServer(providerNotebookPath, e2eNetwork.provider.live);
    }
  }

  #run(label, args) {
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

  #runServer(notebook, endpoint) {
    return this.#services.start(
      [
        "marimo",
        "run",
        notebook,
        "--no-sandbox",
        "--headless",
        "--no-token",
        "--host",
        "127.0.0.1",
        "--port",
        String(endpoint.port),
      ],
      endpoint,
      "run",
      { readyUrl: `${endpoint.origin}/_marimo-studio/status` },
    );
  }

  async close() {
    const results = await Promise.allSettled([this.#preparation.stop(), this.#services.close()]);
    const errors = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    if (errors.length > 0) throw new AggregateError(errors, "Provider workspace shutdown failed");
    await cleanupProviderEnvironment();
  }
}
