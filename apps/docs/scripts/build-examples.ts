import { type ChildProcess, spawn } from "node:child_process";
import { rmSync } from "node:fs";
import { mkdtemp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { constants } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { documentationExampleFamilies, type DocumentationExampleFamily } from "../examples.ts";
import { publishExamples, validatePreparedExample } from "./example-publication.ts";
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
const commandTimings: {
  command: string;
  arguments: readonly string[];
  durationMs: number;
  exitCode: number | null;
}[] = [];
const usage = `Usage: pnpm --filter @marimo-studio/docs examples:build [selectors | --check]

Without selectors, every notebook and view is exported. Each export replaces its
own directory under public/examples as soon as it passes validation.

Selectors may be repeated and combined:
  --family SLUG       Export one notebook and all of its views
  --notebook SLUG     Export one notebook
  --view FAMILY/VIEW  Export one named view

  --check             Validate the complete publication without exporting`;

const isFile = async (path: string): Promise<boolean> => {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
};

let activeCommand: ChildProcess | undefined;

const run = (command: string, arguments_: readonly string[]): Promise<CommandResult> =>
  new Promise((resolveCommand, rejectCommand) => {
    const started = performance.now();
    const child = spawn(command, arguments_, {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        NO_COLOR: "1",
        MARIMO_EXPORT_REPOSITORY:
          process.env.MARIMO_EXPORT_REPOSITORY ?? join(cacheRoot, "export-repository"),
      },
      // Its own process group lets a signal stop the whole export tree, the way a
      // terminal interrupt does.
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    activeCommand = child;
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
      activeCommand = undefined;
      commandTimings.push({
        command,
        arguments: arguments_,
        durationMs: Math.round(performance.now() - started),
        exitCode: code,
      });
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
    "--runtime",
    "zero-python",
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

const validateView = async (
  root: string,
  family: DocumentationExampleFamily,
  view: string,
): Promise<void> => {
  const entrypoint = join(root, family.slug, view, "index.html");
  if (!(await isFile(entrypoint))) {
    throw new Error(`The ${family.slug}/${view} export is unavailable.`);
  }
  await validatePreparedExample(root, family.slug, view);
  const document = await readFile(entrypoint, "utf8");
  for (const match of document.matchAll(/\bhref="\.\.\/([^/"?#]+)\/index\.html"/g)) {
    const target = match[1];
    if (!target || !family.views.some((candidate) => candidate.key === target)) {
      throw new Error(
        `${family.slug}/${view} links to an unexported sibling view: ${target ?? "unknown"}`,
      );
    }
  }
};

const validateExamplePublication = async (root: string): Promise<void> => {
  for (const family of documentationExampleFamilies) {
    if (!(await isFile(join(root, family.slug, "notebook", "index.html")))) {
      throw new Error(`The ${family.slug}/notebook export is unavailable.`);
    }
    for (const view of family.views) {
      await validateView(root, family, view.key);
    }
  }
};

const main = async (): Promise<void> => {
  const arguments_ = process.argv.slice(2);
  if (arguments_.some((argument) => argument === "-h" || argument === "--help")) {
    console.log(usage);
    return;
  }
  if (arguments_.includes("--check")) {
    if (arguments_.length > 1) {
      throw new Error("--check validates the complete publication and takes no other options.");
    }
    await validateExamplePublication(destinationRoot);
    const selection = selectDocumentationExamples(documentationExampleFamilies, []);
    console.log(
      `Validated ${selection.notebooks} static notebooks and ${selection.views} live documentation views.`,
    );
    return;
  }
  const selection = selectDocumentationExamples(documentationExampleFamilies, arguments_);
  await mkdir(cacheRoot, { recursive: true });
  const stagingRoot = await mkdtemp(join(cacheRoot, "docs-examples-"));
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.once(signal, () => {
      // Stop the export first, so it can't write into staging after removal.
      const stop = (): never => {
        rmSync(stagingRoot, { force: true, recursive: true });
        process.exit(128 + constants.signals[signal]);
      };
      const command = activeCommand;
      if (command?.pid === undefined) {
        stop();
      } else {
        command.once("close", stop);
        process.kill(-command.pid, signal);
      }
    });
  }
  // Publish each export as soon as it validates, so an interrupted or failed run
  // keeps every finished export and the last valid copy of the rest.
  const publish = async (slug: string, target: string): Promise<void> => {
    await mkdir(join(destinationRoot, slug), { recursive: true });
    await publishExamples({
      destination: join(destinationRoot, slug, target),
      previous: join(stagingRoot, "previous"),
      staging: join(stagingRoot, slug, target),
    });
  };
  try {
    for (const { family, notebook, views } of selection.families) {
      if (notebook) {
        await exportNotebook(stagingRoot, family.notebook, family.slug);
        await publish(family.slug, "notebook");
      }
      for (const view of views) {
        await exportView(stagingRoot, family.notebook, family.slug, view.key);
        await validateView(stagingRoot, family, view.key);
        await publish(family.slug, view.key);
      }
    }
    console.log(
      `Exported ${selection.notebooks} static notebooks and ${selection.views} live documentation views.`,
    );
  } finally {
    await rm(stagingRoot, { force: true, recursive: true });
    await writeFile(
      join(cacheRoot, "example-timings.json"),
      `${JSON.stringify({ schema: 1, commands: commandTimings }, null, 2)}\n`,
    );
  }
};

main().catch((error: Error) => {
  console.error(error.message);
  process.exitCode = 1;
});
