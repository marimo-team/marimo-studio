import { cp, mkdir, stat } from "node:fs/promises";
import { basename, delimiter, isAbsolute, resolve } from "node:path";

import { createInstalledPackageNetwork } from "./installed-package-network.ts";
import { e2eNetwork } from "./network.ts";
import { NotebookServices } from "./notebook-services.ts";
import { appDirectory, repositoryDirectory } from "./paths.ts";
import { PreparationProcessOwner } from "./preparation-process.ts";

const environmentExecutable = (directory: string, name: string) =>
  resolve(
    directory,
    process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? `${name}.exe` : name,
  );

export class InstalledWorkspace {
  #root: string;
  #preparation = new PreparationProcessOwner();
  #services: NotebookServices | undefined;
  #closing: Promise<void> | undefined;

  constructor(root: string) {
    this.#root = root;
  }

  async prepare(wheel: string) {
    this.#preparation.requireActive();
    if (!isAbsolute(wheel) || !/^marimo_studio-.*\.whl$/.test(basename(wheel))) {
      throw new Error("MARIMO_STUDIO_E2E_WHEEL must name an absolute marimo-studio wheel path");
    }
    if (!(await stat(wheel)).isFile())
      throw new Error(`Installed-package wheel is not a file: ${wheel}`);
    const environmentDirectory = resolve(this.#root, "environment");
    const workspaceDirectory = resolve(this.#root, "workspace");
    const configDirectory = resolve(this.#root, "xdg-config");
    const notebookPath = resolve(workspaceDirectory, "notebook.py");
    const staticDirectory = resolve(this.#root, "static");
    const preparedDirectory = resolve(staticDirectory, "prepared");
    const viewDirectory = resolve(
      workspaceDirectory,
      "__marimo__",
      "studio",
      "notebook",
      "dashboard",
    );
    const python = environmentExecutable(environmentDirectory, "python");
    const studio = environmentExecutable(environmentDirectory, "marimo-studio");

    await mkdir(configDirectory, { recursive: true });
    await cp(resolve(appDirectory, "fixtures-installed"), workspaceDirectory, { recursive: true });
    await this.#preparation.run(
      "create installed-package environment",
      "uv",
      [
        "venv",
        environmentDirectory,
        ...(process.env.MARIMO_STUDIO_E2E_PYTHON
          ? ["--python", process.env.MARIMO_STUDIO_E2E_PYTHON]
          : []),
      ],
      { cwd: repositoryDirectory, stdio: "inherit" },
    );
    this.#preparation.requireActive();
    await this.#preparation.run(
      "install marimo-studio wheel",
      "uv",
      [
        "pip",
        "install",
        "--python",
        python,
        "--no-cache",
        "--exclude-newer-package",
        "marimo-export=false",
        "--exclude-newer-package",
        "marimo-lens=false",
        `${wheel}[lens]`,
        "anywidget>=0.11.0",
      ],
      { cwd: this.#root, stdio: "inherit" },
    );
    this.#preparation.requireActive();

    const environment: NodeJS.ProcessEnv = {
      ...process.env,
      PATH: `${resolve(environmentDirectory, process.platform === "win32" ? "Scripts" : "bin")}${delimiter}${process.env.PATH ?? ""}`,
      PYTHONNOUSERSITE: "1",
      PYTHONSAFEPATH: "1",
      PYTHONUNBUFFERED: "1",
      XDG_CONFIG_HOME: configDirectory,
      MARIMO_EXPORT_REPOSITORY: resolve(this.#root, "export-repository"),
    };
    delete environment.PYTHONHOME;
    delete environment.PYTHONPATH;
    delete environment.UV_PROJECT_ENVIRONMENT;
    delete environment.VIRTUAL_ENV;
    await this.#preparation.run(
      "verify published dependencies",
      python,
      [
        "-c",
        [
          "from importlib.metadata import distribution, version",
          "from pathlib import Path",
          "from packaging.version import Version",
          "import marimo_lens, sys",
          "assert Version(version('marimo-lens')) >= Version('0.2.2')",
          "assert distribution('marimo-lens').read_text('direct_url.json') is None",
          "assert Path(marimo_lens.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())",
          "assert version('marimo-export') == '0.1.0'",
          "assert distribution('marimo-export').read_text('direct_url.json') is None",
        ].join("; "),
      ],
      { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
    );
    this.#preparation.requireActive();
    await this.#preparation.run(
      "create installed Vanilla view",
      studio,
      [
        "view",
        "create",
        "dashboard",
        "--target",
        notebookPath,
        "--starter",
        "marimo-studio/vanilla:default",
        "--json",
      ],
      { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
    );
    this.#preparation.requireActive();
    await cp(resolve(workspaceDirectory, "dashboard.html"), resolve(viewDirectory, "index.html"), {
      force: true,
    });
    await cp(resolve(workspaceDirectory, "states.yaml"), resolve(viewDirectory, "states.yaml"));
    await this.#preparation.run(
      "build installed Vanilla view",
      studio,
      ["view", "build", "dashboard", "--target", notebookPath, "--json"],
      { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
    );
    this.#preparation.requireActive();
    await this.#preparation.run(
      "export installed Vanilla view",
      studio,
      [
        "view",
        "export",
        "dashboard",
        "--target",
        notebookPath,
        "--output",
        staticDirectory,
        "--runtime",
        "wasm",
        "--json",
      ],
      { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
    );
    this.#preparation.requireActive();

    await this.#preparation.run(
      "export installed prepared view",
      studio,
      [
        "view",
        "export",
        "dashboard",
        "--target",
        notebookPath,
        "--output",
        preparedDirectory,
        "--runtime",
        "zero-python",
        "--prepare-timeout",
        "120",
        "--json",
      ],
      { cwd: workspaceDirectory, env: environment, stdio: "inherit" },
    );
    this.#preparation.requireActive();
    const services = new NotebookServices(configDirectory, {
      registryDirectory: resolve(this.#root, "notebook-processes"),
      command: python,
      prefix: [],
      cwd: workspaceDirectory,
      environment,
      forward: { stdout: process.stdout, stderr: process.stderr },
    });
    this.#services = services;
    await services.prepare();
    const marimoArgs = (command: string, target: string[]) => [
      resolve(repositoryDirectory, "apps/e2e/scripts/_compat/server.py"),
      "marimo",
      command,
      ...target,
      "--no-sandbox",
      "--headless",
      "--no-token",
    ];
    const endpoints = e2eNetwork.installed;
    await Promise.all([
      services.start(marimoArgs("edit", [notebookPath]), endpoints.edit, "studio", {
        readyUrl: `${endpoints.edit.origin}/_marimo-studio/status`,
        timeout: 120_000,
      }),
      services.start(marimoArgs("new", []), endpoints.fresh, "studio", { timeout: 120_000 }),
      services.start(marimoArgs("run", [notebookPath]), endpoints.run, "process", {
        readyUrl: `${endpoints.run.origin}/_marimo-studio/status`,
        timeout: 120_000,
      }),
      services.start(
        [
          resolve(repositoryDirectory, "apps/e2e/scripts/static-server.py"),
          "0",
          "--bind",
          "127.0.0.1",
          "--directory",
          staticDirectory,
        ],
        endpoints.static,
        "process",
        { timeout: 120_000 },
      ),
    ]);
    return createInstalledPackageNetwork(endpoints);
  }

  waitForExit() {
    if (!this.#services) throw new Error("Installed workspace has not started");
    return this.#services.waitForExit();
  }

  close() {
    this.#closing ??= this.#close();
    return this.#closing;
  }

  async #close() {
    const results = await Promise.allSettled([this.#preparation.stop(), this.#services?.close()]);
    const errors = results
      .filter((result) => result.status === "rejected")
      .map((result) => result.reason);
    if (errors.length > 0) throw new AggregateError(errors, "Installed workspace shutdown failed");
  }
}
