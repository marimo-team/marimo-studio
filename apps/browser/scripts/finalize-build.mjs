import { readMarimoSource } from "@marimo-studio/marimo-frontend/build-metadata";
import { copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = resolve(packageRoot, "../..");
const output = join(
  workspaceRoot,
  "packages",
  "marimo-studio",
  "src",
  "marimo_studio",
  "_static",
  "server-runtime",
);

const packageManifestCodec = z.codec(z.string(), z.object({ version: z.string().min(1) }), {
  decode: (source, context) => {
    try {
      return JSON.parse(source);
    } catch (error) {
      context.issues.push({
        code: "invalid_format",
        format: "json",
        input: source,
        message: error instanceof Error ? error.message : "Invalid JSON",
      });
      return z.NEVER;
    }
  },
  encode: (manifest) => JSON.stringify(manifest),
});

const buildMetadataSchema = z.object({
  marimo: z.object({
    repository: z.string().min(1),
    version: z.string().min(1),
    commit: z.string().min(1),
  }),
  htmx: z.object({ version: z.string().min(1) }),
});

const packageManifest = async (entry) => {
  let directory = dirname(fileURLToPath(entry));
  while (directory !== dirname(directory)) {
    let source;
    try {
      source = await readFile(join(directory, "package.json"), "utf8");
    } catch {
      directory = dirname(directory);
      continue;
    }
    return packageManifestCodec.decode(source);
  }
  throw new Error(`Cannot find package.json for ${entry}`);
};

const studioStyle = fileURLToPath(import.meta.resolve("@marimo-studio/studio/style.css"));
await copyFile(studioStyle, join(output, "studio.css"));
const styleSource = join(dirname(studioStyle), "styles");
const styleOutput = join(output, "styles");
await mkdir(styleOutput, { recursive: true });
for (const entry of await readdir(styleSource, { withFileTypes: true })) {
  if (entry.isFile() && entry.name.endsWith(".css")) {
    await copyFile(join(styleSource, entry.name), join(styleOutput, entry.name));
  }
}

const marimo = await readMarimoSource();
const htmx = await packageManifest(import.meta.resolve("htmx.org"));
const metadata = buildMetadataSchema.parse({
  marimo: {
    repository: marimo.repository,
    version: marimo.version,
    commit: marimo.commit,
  },
  htmx: { version: htmx.version },
});
await writeFile(join(output, "build-meta.json"), `${JSON.stringify(metadata, null, 2)}\n`);
