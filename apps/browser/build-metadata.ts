import type { Plugin } from "vite";

import { readMarimoSource } from "@marimo-studio/marimo-frontend/build-metadata";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const packageManifestSchema = z.object({ version: z.string().min(1) });

const buildMetadataSchema = z.object({
  marimo: z.object({
    repository: z.string().min(1),
    version: z.string().min(1),
    commit: z.string().min(1),
  }),
  htmx: z.object({ version: z.string().min(1) }),
});

const readPackageManifest = async (entry: string) => {
  let directory = dirname(fileURLToPath(entry));
  while (directory !== dirname(directory)) {
    let source: string;
    try {
      source = await readFile(join(directory, "package.json"), "utf8");
    } catch (error: unknown) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) {
        throw error;
      }
      directory = dirname(directory);
      continue;
    }
    const manifest: unknown = JSON.parse(source);
    return packageManifestSchema.parse(manifest);
  }
  throw new Error(`Cannot find package.json for ${entry}`);
};

export const buildMetadata = (): Plugin => ({
  name: "marimo-studio-build-metadata",
  apply: "build",
  async generateBundle() {
    const marimo = await readMarimoSource();
    const htmx = await readPackageManifest(import.meta.resolve("htmx.org"));
    const metadata = buildMetadataSchema.parse({
      marimo: {
        repository: marimo.repository,
        version: marimo.version,
        commit: marimo.commit,
      },
      htmx: { version: htmx.version },
    });
    this.emitFile({
      type: "asset",
      fileName: "build-meta.json",
      source: `${JSON.stringify(metadata, null, 2)}\n`,
    });
  },
});
