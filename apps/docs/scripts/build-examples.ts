import { spawn } from "node:child_process";
import { cp, mkdtemp, mkdir, readFile, rm, stat } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { documentationExampleFamilies } from "../examples.ts";
import { publishExamples } from "./example-publication.ts";
import { selectDocumentationExamples } from "./example-selection.ts";

interface ExportResult {
  entrypoint: string;
  files: number;
  notebook: string;
  output: string;
  runtime: string;
  schema: number;
  preflight: {
    ok: boolean;
  };
  warnings: unknown[];
  view: string;
}

interface CommandResult {
  stdout: string;
}

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const repositoryRoot = resolve(packageRoot, "../..");
const publicRoot = join(packageRoot, "public");
const destinationRoot = join(publicRoot, "examples");
const cacheRoot = join(packageRoot, ".vitepress", "cache");
const usage = `Usage: pnpm --filter @marimo-studio/docs examples:build [selectors]

Selectors may be repeated and combined:
  --family SLUG       Rebuild one notebook and all of its views
  --notebook SLUG     Rebuild one notebook export
  --view FAMILY/VIEW  Rebuild one named view export`;

const isFile = async (path: string): Promise<boolean> => {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
};

const isDirectory = async (path: string): Promise<boolean> => {
  try {
    return (await stat(path)).isDirectory();
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

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      process.stderr.write(chunk);
    });
    child.on("error", rejectCommand);
    child.on("close", (code) => {
      if (code === 0) {
        resolveCommand({ stdout });
        return;
      }
      rejectCommand(
        new Error(
          `${command} ${arguments_.join(" ")} exited with ${code ?? "no status"}.\n${stdout}`,
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
  await rm(output, { force: true, recursive: true });
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

  if (
    result.schema !== 1 ||
    result.runtime !== "zero-python" ||
    result.preflight?.ok !== true ||
    !Array.isArray(result.warnings) ||
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
  await rm(output, { force: true, recursive: true });
  await mkdir(output, { recursive: true });
  console.log(`Exporting ${slug}/notebook`);
  await run("uv", [
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

const validateExamplePublication = async (root: string): Promise<void> => {
  for (const family of documentationExampleFamilies) {
    const notebook = join(root, family.slug, "notebook", "index.html");
    if (!(await isFile(notebook))) {
      throw new Error(`The ${family.slug}/notebook export is unavailable.`);
    }
    for (const view of family.views) {
      const entrypoint = join(root, family.slug, view.key, "index.html");
      if (!(await isFile(entrypoint))) {
        throw new Error(`The ${family.slug}/${view.key} export is unavailable.`);
      }
      const document = await readFile(entrypoint, "utf8");
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
};

const main = async (): Promise<void> => {
  const arguments_ = process.argv.slice(2);
  if (arguments_.some((argument) => argument === "-h" || argument === "--help")) {
    console.log(usage);
    return;
  }
  const selection = selectDocumentationExamples(documentationExampleFamilies, arguments_);
  await mkdir(cacheRoot, { recursive: true });
  const stagingRoot = await mkdtemp(join(cacheRoot, "docs-examples-"));
  try {
    if (!selection.complete) {
      if (!(await isDirectory(destinationRoot))) {
        throw new Error(
          "Selective example rebuilding requires an existing complete publication. Run the full examples build first.",
        );
      }
      await validateExamplePublication(destinationRoot);
      await cp(destinationRoot, stagingRoot, {
        errorOnExist: false,
        force: true,
        recursive: true,
      });
    }
    for (const selected of selection.families) {
      const { family } = selected;
      if (selected.notebook) {
        await exportNotebook(stagingRoot, family.notebook, family.slug);
      }
      for (const view of selected.views) {
        await exportView(stagingRoot, family.notebook, family.slug, view.key);
      }
    }

    await validateExamplePublication(stagingRoot);

    await publishExamples({
      destination: destinationRoot,
      previous: join(cacheRoot, `docs-examples-previous-${process.pid}`),
      staging: stagingRoot,
    });
    const action = selection.complete ? "Exported" : "Rebuilt";
    console.log(
      `${action} ${selection.notebooks} static notebooks and ${selection.views} live documentation views.`,
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
