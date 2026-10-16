import type { Plugin } from "vite";

import { readMarimoSource } from "@marimo-studio/marimo-frontend/build-metadata";
import { createHash } from "node:crypto";
import { type Dirent, existsSync } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const packageManifestSchema = z.object({ version: z.string().min(1) });

const buildMetadataSchema = z.object({
  marimo: z.object({
    repository: z.string().min(1),
    version: z.string().min(1),
    commit: z.string().min(1),
    patchSha256: z.string().min(1),
  }),
  marimoExport: z.object({ version: z.string().min(1) }),
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
    const marimoExport = await readPackageManifest(
      import.meta.resolve("@marimo-team/marimo-export/package.json"),
    );
    const metadata = buildMetadataSchema.parse({
      marimo: {
        repository: marimo.repository,
        version: marimo.version,
        commit: marimo.commit,
        patchSha256: marimo.patchSha256,
      },
      marimoExport: { version: marimoExport.version },
    });
    this.emitFile({
      type: "asset",
      fileName: "build-meta.json",
      source: `${JSON.stringify(metadata, null, 2)}\n`,
    });
  },
});

export const buildSourcesSchema = z
  .object({
    output: z.string().min(1),
    files: z.record(z.string().min(1), z.string().regex(/^[0-9a-f]{64}$/)),
  })
  .strict();

export type BuildSources = z.infer<typeof buildSourcesSchema>;

const toPosix = (path: string) => path.split(sep).join("/");

// Paths below dot directories, such as the prepared marimo checkout under
// `.cache`, and below `node_modules` are identified by `build-meta.json` and
// `pnpm-lock.yaml`.
const workspacePath = (root: string, file: string): string | undefined => {
  const path = relative(root, file);
  if (
    path === "" ||
    isAbsolute(path) ||
    path.split(sep).some((segment) => segment.startsWith(".") || segment === "node_modules")
  ) {
    return undefined;
  }
  return path;
};

const ownerPackage = (root: string, file: string): string | undefined => {
  let directory = dirname(file);
  while (workspacePath(root, directory) !== undefined) {
    if (existsSync(join(directory, "package.json"))) {
      return directory;
    }
    directory = dirname(directory);
  }
  return undefined;
};

const treeFiles = async (directory: string): Promise<string[]> => {
  let entries: Dirent[];
  try {
    entries = await readdir(directory, { withFileTypes: true });
  } catch (error: unknown) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return [];
    }
    throw error;
  }
  const nested = await Promise.all(
    entries
      .filter((entry) => !entry.name.startsWith(".") && entry.name !== "node_modules")
      .map(async (entry) => {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) {
          return treeFiles(path);
        }
        return entry.isFile() ? [path] : [];
      }),
  );
  return nested.flat();
};

/**
 * Return the files that shape a build as sorted paths relative to `root`: the
 * workspace files among `moduleIds`, the `package.json` and `src` tree of each
 * package that owns one, the workspace `configFiles`, and `pnpm-lock.yaml`. A package's
 * `src` tree also covers files the module graph does not list, such as CSS
 * `@import` partials and modules that only a worker build reads.
 */
export const workspaceSources = async (
  root: string,
  moduleIds: Iterable<string>,
  configFiles: Iterable<string>,
): Promise<string[]> => {
  const modules: string[] = [];
  const packages = new Set<string>();
  for (const id of moduleIds) {
    const [file = ""] = id.split("?", 1);
    if (id.startsWith("\0") || !isAbsolute(file) || workspacePath(root, file) === undefined) {
      continue;
    }
    modules.push(file);
    const owner = ownerPackage(root, file);
    if (owner !== undefined) {
      packages.add(owner);
    }
  }
  const files = [
    join(root, "pnpm-lock.yaml"),
    ...modules,
    ...configFiles,
    ...[...packages].map((directory) => join(directory, "package.json")),
    ...(
      await Promise.all([...packages].map((directory) => treeFiles(join(directory, "src"))))
    ).flat(),
  ];
  const paths = new Set<string>();
  for (const file of files) {
    const path = workspacePath(root, file);
    if (path !== undefined) {
      paths.add(toPosix(path));
    }
  }
  return [...paths].sort();
};

/** Return the SHA-256 of `content` with LF line endings, matching CRLF and LF checkouts. */
export const sourceDigest = (content: Buffer): string =>
  createHash("sha256")
    .update(content.toString("latin1").replaceAll("\r\n", "\n"), "latin1")
    .digest("hex");

/**
 * Record the content of the files that shape the build, so a source checkout
 * can tell when its browser assets no longer match their sources.
 */
export const buildSources = ({ root, fileName }: { root: string; fileName: string }): Plugin => {
  let configFiles: readonly string[] = [];
  let started = 0;
  return {
    name: "marimo-studio-build-sources",
    apply: "build",
    configResolved(config) {
      configFiles = [
        ...(config.configFile === undefined ? [] : [config.configFile]),
        ...config.configFileDependencies,
      ];
    },
    buildStart() {
      started = Date.now();
    },
    async generateBundle(outputOptions) {
      if (outputOptions.dir === undefined) {
        throw new Error("Browser build sources require a directory build output.");
      }
      const paths = await workspaceSources(root, this.getModuleIds(), configFiles);
      const digests = await Promise.all(
        paths.map(async (path) => {
          const file = join(root, path);
          const [content, stats] = await Promise.all([readFile(file), stat(file)]);
          // A digest read after a later edit would describe code the bundle lacks.
          if (stats.mtimeMs > started) {
            throw new Error(
              `${path} changed while the browser assets were building. Run \`make build\` again.`,
            );
          }
          return [path, sourceDigest(content)] as const;
        }),
      );
      const sources: BuildSources = {
        output: toPosix(relative(root, outputOptions.dir)),
        files: Object.fromEntries(digests),
      };
      this.emitFile({
        type: "asset",
        fileName,
        source: `${JSON.stringify(sources, null, 2)}\n`,
      });
    },
  };
};
