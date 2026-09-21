import { z } from "zod";

import { e2eNetwork } from "../scripts/network.ts";
import { collaborativeNotebookPath, notebookPath, repositoryDirectory } from "../scripts/paths.ts";
import { PreparationProcessOwner } from "../scripts/preparation-process.ts";

const CLI_PROCESS_TIMEOUT = 90_000;
const workspaceCheckSchema = z.object({ ok: z.boolean() });
const workspaceShowSchema = z.object({
  schema: z.literal(1),
  notebook: z.string(),
  view: z.string(),
  generation: z.number().int().positive(),
  client_id: z.string(),
  session_id: z.string(),
  preview_url: z.string().url(),
  frame_selector: z.string(),
});

export class StudioCli {
  readonly #processes = new PreparationProcessOwner();

  close(): Promise<void> {
    return this.#processes.stop("SIGTERM");
  }

  bindWorkspaceCell(alias: string, cell: number) {
    return this.#run(["notebook", "bind", alias, "--target", notebookPath, "--cell", String(cell)]);
  }

  addWorkspaceView(target: string, name: string, starter?: string) {
    return this.#run([
      "view",
      "create",
      name,
      "--target",
      target,
      ...(starter ? ["--starter", starter] : []),
    ]);
  }

  buildWorkspaceView(name: string, target = notebookPath) {
    return this.#run(["view", "build", name, "--target", target, "--profile", "development"]);
  }

  async holdWorkspacePublication(name: string) {
    const { stdout } = await this.#run([
      "view",
      "hold",
      name,
      "--target",
      notebookPath,
      "--owner",
      "browser-acceptance",
      "--ttl",
      "300",
      "--json",
    ]);
    return z.object({ token: z.string().min(1) }).parse(JSON.parse(stdout)).token;
  }

  releaseWorkspacePublication(name: string, token: string) {
    return this.#run(["view", "release", name, "--target", notebookPath, "--token", token]);
  }

  exportWorkspaceView(name: string, target: string, output: string) {
    return this.#run(["view", "export", name, "--target", target, "--output", output]);
  }

  addCollaborativeView(name: string) {
    return this.#run(["view", "create", name, "--target", collaborativeNotebookPath]);
  }

  async activateWorkspaceView(view: string, browserClient?: string) {
    const args = [
      "view",
      "show",
      view,
      "--target",
      notebookPath,
      "--server",
      `${e2eNetwork.main.studio.origin}?file=notebook.py`,
      "--json",
    ];
    if (browserClient) args.push("--browser-client", browserClient);
    const { stdout } = await this.#run(args);
    return workspaceShowSchema.parse(JSON.parse(stdout));
  }

  async previewWorkspaceView(
    view: string,
    runtime: "server" | "wasm" | "zero-python",
    exact = false,
  ) {
    const { stdout } = await this.#run([
      "view",
      "preview",
      view,
      "--target",
      notebookPath,
      "--server",
      `${e2eNetwork.main.studio.origin}?file=notebook.py`,
      "--runtime",
      runtime,
      ...(exact ? ["--exact"] : []),
      "--json",
    ]);
    return z.string().url().parse(JSON.parse(stdout));
  }

  async checkWorkspace(): Promise<boolean> {
    const { stdout } = await this.#run(["validate", "--target", notebookPath, "--json"]);
    return workspaceCheckSchema.parse(JSON.parse(stdout)).ok;
  }

  #run(args: string[]) {
    return this.#processes.runCaptured(
      `marimo-studio ${args.join(" ")}`,
      "uv",
      ["run", "--frozen", "--group", "e2e", "marimo-studio", ...args],
      { cwd: repositoryDirectory },
      { timeout: CLI_PROCESS_TIMEOUT },
    );
  }
}
