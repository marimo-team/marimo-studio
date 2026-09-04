import type { Plugin } from "vite";

import { existsSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

interface ViteChunkMetadata {
  readonly importedAssets?: ReadonlySet<string>;
  readonly importedCss?: ReadonlySet<string>;
}

export interface BrowserRenderedModule {
  readonly code?: Uint8Array | null;
  readonly originalLength?: number;
  readonly removedExports?: readonly string[];
  readonly renderedExports?: readonly string[];
  readonly renderedLength?: number;
}

export interface BrowserChunk {
  readonly type: "chunk";
  readonly fileName: string;
  readonly name: string;
  readonly isEntry: boolean;
  readonly imports: readonly string[];
  readonly dynamicImports: readonly string[];
  readonly referencedFiles?: readonly string[];
  readonly modules: Readonly<Record<string, BrowserRenderedModule>>;
  readonly viteMetadata?: ViteChunkMetadata;
}

interface BrowserAsset {
  readonly type: "asset";
}

interface ChunkClosureOptions {
  readonly excludeDynamic?: (chunk: BrowserChunk) => boolean;
  readonly includeDynamic?: boolean;
}

export type BrowserBundle = Record<string, BrowserChunk | BrowserAsset>;

export interface BrowserEntryClosure {
  readonly script: string;
  readonly styles: readonly string[];
  readonly assets: readonly string[];
}

export interface BrowserEntryClosures {
  readonly schema: 1;
  readonly entries: Readonly<Record<string, BrowserEntryClosure>>;
}

export interface EntryClosurePluginOptions {
  readonly entries?: readonly (typeof ENTRY_NAMES)[number][];
  readonly fileName?: string;
}

const ENTRY_NAMES = ["runtime", "zero-python"] as const;
// Static browser entries are self-contained. Add an external here only with a
// matching deployment contract and regression.
const EXPLICIT_EXTERNAL_BUNDLE_REFERENCES: ReadonlySet<string> = new Set();
const PRUNED_KATEX_FONT = /^assets\/KaTeX_.+\.(?:ttf|woff)$/u;
const FORBIDDEN_ZERO_PYTHON_MODULES = [
  /\/runtime\/(?:server|transport|wasm)\.ts$/u,
  /\/values\/(?:remote|wasm)\.ts$/u,
  /\/outputs\/(?:remote|wasm)\.ts$/u,
  /\/wasm-rpc\.ts$/u,
  /\/embedded-runtime/u,
  /\/server-only-rtc\.ts$/u,
  /\/session-bootstrap/u,
  /\/upstream\/(?:runtime|session)\.ts$/u,
  /(?:^|\/)pyodide(?:\/|$)/iu,
  /(?:^|\/)worker(?:-factory)?\.[cm]?[jt]sx?$/iu,
];

const isChunk = (value: BrowserBundle[string]): value is BrowserChunk => value.type === "chunk";

const safePath = (value: string): string => {
  if (
    value.length === 0 ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.split("/").includes("..")
  ) {
    throw new Error(`Browser entry closure contains an unsafe path ${JSON.stringify(value)}`);
  }
  return value;
};

const entryChunk = (bundle: BrowserBundle, name: string): BrowserChunk => {
  const entry = Object.values(bundle).find(
    (value): value is BrowserChunk => isChunk(value) && value.isEntry && value.name === name,
  );
  if (!entry) {
    throw new Error(`Browser build is missing entry ${JSON.stringify(name)}`);
  }
  return entry;
};

const bundleReference = (
  bundle: BrowserBundle,
  owner: string,
  kind: string,
  fileName: string,
): BrowserBundle[string] | undefined => {
  const path = safePath(fileName);
  const output = bundle[path];
  if (output !== undefined) {
    return output;
  }
  if (EXPLICIT_EXTERNAL_BUNDLE_REFERENCES.has(path)) {
    return undefined;
  }
  // The Marimo build removes legacy KaTeX fonts after Vite records CSS asset metadata.
  if (kind === "asset" && PRUNED_KATEX_FONT.test(path)) {
    return undefined;
  }
  throw new Error(
    `Browser entry closure owner ${JSON.stringify(owner)} ${kind} ${JSON.stringify(path)} has no emitted bundle record`,
  );
};

const isCssOnlyFacade = (chunk: BrowserChunk): boolean => {
  const modules = Object.entries(chunk.modules);
  return (
    modules.length > 0 &&
    (chunk.viteMetadata?.importedCss?.size ?? 0) > 0 &&
    chunk.imports.length === 0 &&
    chunk.dynamicImports.length === 0 &&
    modules.every(([moduleId, module]) => moduleId.endsWith(".css") && module.renderedLength === 0)
  );
};

const isRuntimeZeroPythonImplementationModule = (moduleId: string): boolean =>
  (moduleId.includes("/marimo-export/") && !moduleId.includes("/packages/portable-json/")) ||
  /\/apps\/browser\/src\/zero-python\/(?!runtime\.ts$)/u.test(moduleId);

const containsRuntimeZeroPythonImplementation = (chunk: BrowserChunk): boolean =>
  Object.keys(chunk.modules).some(isRuntimeZeroPythonImplementationModule);

const chunkClosure = (
  bundle: BrowserBundle,
  entry: BrowserChunk,
  { excludeDynamic, includeDynamic = true }: ChunkClosureOptions = {},
): readonly BrowserChunk[] => {
  const result: BrowserChunk[] = [];
  const visited = new Set<string>();
  const visit = (chunk: BrowserChunk): void => {
    if (visited.has(chunk.fileName)) {
      return;
    }
    visited.add(chunk.fileName);
    const dependencies = includeDynamic
      ? [...chunk.imports, ...chunk.dynamicImports]
      : chunk.imports;
    for (const fileName of dependencies) {
      const dynamicImport =
        !chunk.imports.includes(fileName) && chunk.dynamicImports.includes(fileName);
      const kind = dynamicImport ? "dynamic import" : "import";
      const imported = bundleReference(bundle, chunk.fileName, kind, fileName);
      if (imported === undefined) {
        continue;
      }
      if (!isChunk(imported)) {
        throw new Error(
          `Browser entry closure owner ${JSON.stringify(chunk.fileName)} ${kind} ${JSON.stringify(fileName)} is not a chunk`,
        );
      }
      if (dynamicImport && excludeDynamic?.(imported) === true) {
        continue;
      }
      visit(imported);
    }
    result.push(chunk);
  };
  visit(entry);
  return result;
};

const orderedStyles = (
  bundle: BrowserBundle,
  chunks: readonly BrowserChunk[],
): readonly string[] => {
  const styles: string[] = [];
  const seen = new Set<string>();
  for (const chunk of chunks) {
    for (const fileName of chunk.viteMetadata?.importedCss ?? []) {
      const path = safePath(fileName);
      const output = bundleReference(bundle, chunk.fileName, "CSS", path);
      if (output === undefined) {
        continue;
      }
      if (output.type !== "asset") {
        throw new Error(
          `Browser entry closure owner ${JSON.stringify(chunk.fileName)} CSS ${JSON.stringify(path)} is not an asset`,
        );
      }
      if (!seen.has(path)) {
        seen.add(path);
        styles.push(path);
      }
    }
  }
  return Object.freeze(styles);
};

const closureAssets = (
  bundle: BrowserBundle,
  entry: BrowserChunk,
  chunks: readonly BrowserChunk[],
  styles: readonly string[],
): readonly string[] => {
  const excluded = new Set([entry.fileName, ...styles]);
  const assets = new Set<string>();
  const add = (owner: string, kind: string, fileName: string): void => {
    const path = safePath(fileName);
    const output = bundleReference(bundle, owner, kind, path);
    if (output !== undefined && !excluded.has(path)) {
      assets.add(path);
    }
  };
  for (const chunk of chunks) {
    // Rolldown retains zero-length CSS facade records after extracting their
    // styles, but writes no JavaScript file for those records.
    if (!isCssOnlyFacade(chunk)) {
      add(chunk.fileName, "chunk", chunk.fileName);
    }
    for (const fileName of chunk.viteMetadata?.importedAssets ?? []) {
      add(chunk.fileName, "asset", fileName);
    }
    for (const fileName of chunk.referencedFiles ?? []) {
      add(chunk.fileName, "referenced file", fileName);
    }
  }
  return Object.freeze(Array.from(assets).sort());
};

const assertZeroPythonModules = (chunks: readonly BrowserChunk[]): void => {
  const forbidden = chunks.flatMap((chunk) =>
    Object.keys(chunk.modules).filter((moduleId) =>
      FORBIDDEN_ZERO_PYTHON_MODULES.some((pattern) => pattern.test(moduleId)),
    ),
  );
  if (forbidden.length > 0) {
    throw new Error(
      `Zero-Python entry imports forbidden execution modules: ${forbidden.sort().join(", ")}`,
    );
  }
};

const assertRuntimeModules = (chunks: readonly BrowserChunk[]): void => {
  const forbidden = chunks.flatMap((chunk) =>
    Object.keys(chunk.modules).filter(isRuntimeZeroPythonImplementationModule),
  );
  if (forbidden.length > 0) {
    throw new Error(
      `Runtime closure imports Zero-Python implementation modules: ${forbidden.sort().join(", ")}`,
    );
  }
};

export const buildEntryClosures = (
  bundle: BrowserBundle,
  entryNames: readonly (typeof ENTRY_NAMES)[number][] = ENTRY_NAMES,
): BrowserEntryClosures => {
  const entries: Record<string, BrowserEntryClosure> = {};
  for (const name of entryNames) {
    const entry = entryChunk(bundle, name);
    const chunks = chunkClosure(
      bundle,
      entry,
      name === "runtime" ? { excludeDynamic: containsRuntimeZeroPythonImplementation } : undefined,
    );
    if (name === "zero-python") {
      assertZeroPythonModules(chunks);
    } else {
      assertRuntimeModules(chunks);
    }
    const styles = orderedStyles(bundle, chunks);
    entries[name] = Object.freeze({
      script: safePath(entry.fileName),
      styles,
      assets: closureAssets(bundle, entry, chunks, styles),
    });
  }
  return Object.freeze({ schema: 1, entries: Object.freeze(entries) });
};

export const validateWrittenEntryClosures = (
  closures: BrowserEntryClosures,
  emitted: ReadonlySet<string>,
): BrowserEntryClosures => {
  for (const [name, entry] of Object.entries(closures.entries)) {
    for (const [kind, paths] of [
      ["script", [entry.script]],
      ["style", entry.styles],
      ["asset", entry.assets],
    ] as const) {
      for (const path of paths) {
        if (!emitted.has(path)) {
          throw new Error(
            `Browser entry closure ${JSON.stringify(name)} ${kind} ${JSON.stringify(path)} was not written`,
          );
        }
      }
    }
  }
  return closures;
};

export const entryClosures = ({
  entries = ENTRY_NAMES,
  fileName = "entry-closures.json",
}: EntryClosurePluginOptions = {}): Plugin => {
  let generated: BrowserEntryClosures | undefined;
  return {
    name: "marimo-studio-entry-closures",
    generateBundle(_options, bundle) {
      // SAFETY: Rolldown supplies chunk and asset records matching the fields consumed above.
      const browserBundle = bundle as BrowserBundle;
      generated = buildEntryClosures(browserBundle, entries);
      this.emitFile({
        type: "asset",
        fileName,
        source: `${JSON.stringify(generated, null, 2)}\n`,
      });
    },
    writeBundle(outputOptions) {
      if (generated === undefined || outputOptions.dir === undefined) {
        throw new Error("Browser entry closure requires a directory build output.");
      }
      const outputRoot = outputOptions.dir;
      const paths = Object.values(generated.entries).flatMap((entry) => [
        entry.script,
        ...entry.styles,
        ...entry.assets,
      ]);
      const emitted = new Set(
        paths.filter((path) => {
          const output = join(outputRoot, path);
          return existsSync(output) && statSync(output).isFile();
        }),
      );
      validateWrittenEntryClosures(generated, emitted);
      writeFileSync(join(outputRoot, fileName), `${JSON.stringify(generated, null, 2)}\n`, "utf8");
    },
  };
};
