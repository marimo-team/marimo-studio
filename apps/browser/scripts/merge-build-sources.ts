import { readFile, unlink, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import { type BuildSources, buildSourcesSchema } from "../build-metadata.ts";

const outputRoot = resolve(
  import.meta.dirname,
  "../../../packages/marimo-studio/src/marimo_studio/_static/browser",
);
const partialPaths = ["build-sources.runtime.json", "build-sources.zero-python.json"].map((name) =>
  join(outputRoot, name),
);
// The record sits beside the served asset directory.
const outputPath = join(outputRoot, "..", "build-sources.json");

const partials = await Promise.all(
  partialPaths.map(async (path) =>
    buildSourcesSchema.parse(JSON.parse(await readFile(path, "utf8"))),
  ),
);
const [first] = partials;
if (first === undefined || partials.some((partial) => partial.output !== first.output)) {
  throw new Error("Browser builds must record sources for the same output directory.");
}
const files: Record<string, string> = {};
for (const partial of partials) {
  for (const [path, digest] of Object.entries(partial.files)) {
    if (files[path] !== undefined && files[path] !== digest) {
      throw new Error(
        `${path} changed while the browser assets were building. Run \`make build\` again.`,
      );
    }
    files[path] = digest;
  }
}
const sources: BuildSources & { readonly schema: 1 } = {
  schema: 1,
  output: first.output,
  files: Object.fromEntries(
    Object.keys(files)
      .sort()
      .map((path) => [path, files[path]]),
  ),
};
await writeFile(outputPath, `${JSON.stringify(sources, null, 2)}\n`, "utf8");
await Promise.all(partialPaths.map((path) => unlink(path)));
