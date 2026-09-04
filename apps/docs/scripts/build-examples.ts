import { spawn } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, stat } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { documentationExampleFamilies } from "../examples.ts";
import { publishExamples } from "./example-publication.ts";

interface ExportResult {
  entrypoint: string;
  files: number;
  notebook: string;
  output: string;
  runtime: string;
  schema: number;
  view: string;
}

interface CommandResult {
  stderr: string;
  stdout: string;
}

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const repositoryRoot = resolve(packageRoot, "../..");
const publicRoot = join(packageRoot, "public");
const destinationRoot = join(publicRoot, "examples");
const cacheRoot = join(packageRoot, ".vitepress", "cache");

const isFile = async (path: string): Promise<boolean> => {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
};

const run = (command: string, arguments_: readonly string[]): Promise<CommandResult> =>
  new Promise((resolveCommand, rejectCommand) => {
    const child = spawn(command, arguments_, {
      cwd: repositoryRoot,
      env: { ...process.env, NO_COLOR: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.on("error", rejectCommand);
    child.on("close", (code) => {
      if (code === 0) {
        resolveCommand({ stderr, stdout });
        return;
      }
      rejectCommand(
        new Error(
          `${command} ${arguments_.join(" ")} exited with ${code ?? "no status"}.\n${stderr}${stdout}`,
        ),
      );
    });
  });

const exportView = async (
  stagingRoot: string,
  notebook: string,
  slug: string,
  view: string,
): Promise<void> => {
  const output = join(stagingRoot, slug, view);
  console.log(`Exporting ${slug}/${view}`);
  const command = await run("uv", [
    "run",
    "--frozen",
    "marimo-studio",
    "view",
    "export",
    view,
    "--target",
    notebook,
    "--output",
    output,
    "--prepare-timeout",
    "900",
    "--json",
  ]);
  // SAFETY: The same-worktree CLI owns schema 1. The checks below bind its
  // paths, runtime, view, and file count before the generated tree is published.
  const result = JSON.parse(command.stdout) as ExportResult;
  const entrypoint = join(output, "index.html");

  if (command.stderr.trim()) {
    process.stderr.write(command.stderr);
  }

  if (
    result.schema !== 1 ||
    result.runtime !== "zero-python" ||
    result.view !== view ||
    result.files < 1 ||
    resolve(result.entrypoint) !== resolve(entrypoint) ||
    resolve(result.notebook) !== resolve(repositoryRoot, notebook) ||
    resolve(result.output) !== resolve(output) ||
    !(await isFile(entrypoint))
  ) {
    throw new Error(`The ${slug}/${view} export returned an invalid result.`);
  }

  const document = await readFile(entrypoint, "utf8");
  if (!document.includes('<base href="./">')) {
    throw new Error(`The ${slug}/${view} export has no document-relative base.`);
  }
  if (/\b(?:href|src)="\/(?!\/)/.test(document)) {
    throw new Error(`The ${slug}/${view} export contains a root-absolute asset URL.`);
  }
};

const exportNotebook = async (
  stagingRoot: string,
  notebook: string,
  slug: string,
): Promise<void> => {
  const output = join(stagingRoot, slug, "notebook");
  const entrypoint = join(output, "index.html");
  await mkdir(output, { recursive: true });
  console.log(`Exporting ${slug}/notebook`);
  const command = await run("uv", [
    "run",
    "--frozen",
    "marimo",
    "export",
    "html",
    notebook,
    "--sandbox",
    "--output",
    entrypoint,
  ]);
  if (command.stderr.trim()) {
    process.stderr.write(command.stderr);
  }
  if (!(await isFile(entrypoint))) {
    throw new Error(`The ${slug} notebook export did not create index.html.`);
  }

  const document = await readFile(entrypoint, "utf8");
  if (
    !document.includes(`<marimo-filename hidden>${basename(notebook)}</marimo-filename>`) ||
    !document.includes("<marimo-code hidden")
  ) {
    throw new Error(`The ${slug} notebook export is missing its source or captured session.`);
  }
};

const main = async (): Promise<void> => {
  await mkdir(cacheRoot, { recursive: true });
  const stagingRoot = await mkdtemp(join(cacheRoot, "docs-examples-"));
  try {
    for (const family of documentationExampleFamilies) {
      await exportNotebook(stagingRoot, family.notebook, family.slug);
      for (const view of family.views) {
        await exportView(stagingRoot, family.notebook, family.slug, view.key);
      }
    }

    for (const family of documentationExampleFamilies) {
      for (const view of family.views) {
        const document = await readFile(
          join(stagingRoot, family.slug, view.key, "index.html"),
          "utf8",
        );
        for (const match of document.matchAll(/\bhref="\.\.\/([^/"?#]+)\/index\.html"/g)) {
          const target = match[1];
          if (!target || !family.views.some((candidate) => candidate.key === target)) {
            throw new Error(
              `${family.slug}/${view.key} links to an unexported sibling view: ${target ?? "unknown"}`,
            );
          }
        }
      }
    }

    await publishExamples({
      destination: destinationRoot,
      previous: join(cacheRoot, `docs-examples-previous-${process.pid}`),
      staging: stagingRoot,
    });
    console.log(
      `Exported ${documentationExampleFamilies.length} static notebooks and ${documentationExampleFamilies.reduce((count, family) => count + family.views.length, 0)} live documentation views.`,
    );
  } catch (error) {
    await rm(stagingRoot, { force: true, recursive: true });
    throw error;
  }
};

main().catch((error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
