import type { Plugin } from "vite";

import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { readMarimoSourceSync } from "../scripts/metadata.mjs";
import { createWasmWorkerViteIntegration } from "./wasm-worker-vite.ts";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const katexSourcePattern =
  /src:\s*(url\([^)]*\)\s*format\("woff2"\)),\s*url\([^)]*\.woff[^)]*\)\s*format\("woff"\),\s*url\([^)]*\.ttf[^)]*\)\s*format\("truetype"\);?/g;

export const evergreenKaTeXFontCss = (source: string): string => {
  const transformed = source.replace(katexSourcePattern, "src: $1;");
  const unsupported = transformed.search(/format\("(?:woff|truetype)"\)/);
  if (unsupported >= 0) {
    throw new Error(
      `KaTeX font CSS contains a non-WOFF2 browser source: ${transformed.slice(
        Math.max(0, unsupported - 160),
        unsupported + 240,
      )}`,
    );
  }
  return transformed;
};

const tableHeaderRef = `            ref={(thead) => {
              columnSizingHandler({ table, column: header.column, thead });
            }}`;
const stableTableHeaderRef = "            ref={studioColumnSizingRef(table, header.column)}";
const tableRendererAnchor = "export function renderTableHeader<TData>(";
const tableHeaderRefOwner = `type StudioTableHeaderRef = (
  thead: HTMLTableCellElement | null,
) => (() => void) | void;

const studioColumnSizingRefs = new WeakMap<
  object,
  WeakMap<object, StudioTableHeaderRef>
>();

const studioColumnSizingRef = <TData,>(
  table: Table<TData>,
  column: Column<TData>,
): StudioTableHeaderRef => {
  let columns = studioColumnSizingRefs.get(table);
  if (!columns) {
    columns = new WeakMap();
    studioColumnSizingRefs.set(table, columns);
  }
  let ref = columns.get(column);
  if (!ref) {
    ref = (thead) => {
      if (!thead) {
        return;
      }
      const measure = () => columnSizingHandler({ table, column, thead });
      measure();
      if (typeof ResizeObserver === "undefined") {
        return;
      }
      const observer = new ResizeObserver(measure);
      observer.observe(thead);
      return () => observer.disconnect();
    };
    columns.set(column, ref);
  }
  return ref;
};

`;

export const stabilizeDataTableHeaderRefs = (source: string): string => {
  if (!source.includes(tableHeaderRef) || !source.includes(tableRendererAnchor)) {
    throw new Error("Marimo data table header refs no longer match the React 19 adapter");
  }
  return source
    .replace(tableHeaderRef, stableTableHeaderRef)
    .replace(tableRendererAnchor, `${tableHeaderRefOwner}${tableRendererAnchor}`);
};

const missingCellScrollWarnings = [
  '    Logger.warn("scrollCellIntoView: element not found");\n',
  `    Logger.warn(
      \`[CellFocusManager] scrollCellIntoView: element not found: \${cellId}\`,
    );
`,
] as const;

export const silenceMissingPresentationCellScroll = (source: string): string => {
  if (!missingCellScrollWarnings.every((warning) => source.includes(warning))) {
    throw new Error("Marimo cell scrolling no longer matches the presentation adapter");
  }
  return missingCellScrollWarnings.reduce(
    (current, warning) => current.replaceAll(warning, ""),
    source,
  );
};

const evergreenKaTeXFonts = (): Plugin => ({
  name: "marimo-studio-evergreen-katex-fonts",
  enforce: "pre",
  transform(source, id) {
    const path = id.split("?", 1)[0];
    if (path?.endsWith("/css/katex-fonts.css") || path?.endsWith("/dist/katex.css")) {
      return { code: evergreenKaTeXFontCss(source), map: null };
    }
  },
  generateBundle(_options, bundle) {
    for (const output of Object.values(bundle)) {
      if (output.type === "asset" && output.fileName.endsWith(".css")) {
        const source =
          output.source instanceof Uint8Array
            ? new TextDecoder().decode(output.source)
            : output.source;
        output.source = evergreenKaTeXFontCss(source);
      }
    }
    for (const [fileName, output] of Object.entries(bundle)) {
      if (output.type === "asset" && /(?:^|\/)KaTeX_[^/]+\.(?:woff|ttf)$/.test(fileName)) {
        delete bundle[fileName];
      }
    }
  },
});

const stableDataTableHeaderRefs = (): Plugin => ({
  name: "marimo-studio-stable-data-table-header-refs",
  enforce: "pre",
  transform(source, id) {
    const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
    if (path?.endsWith("/components/data-table/renderers.tsx")) {
      return { code: stabilizeDataTableHeaderRefs(source), map: null };
    }
  },
});

const quietPresentationCellScroll = (): Plugin => ({
  name: "marimo-studio-quiet-presentation-cell-scroll",
  enforce: "pre",
  transform(source, id) {
    const path = id.split("?", 1)[0]?.replaceAll("\\", "/");
    if (path?.endsWith("/core/cells/scrollCellIntoView.ts")) {
      return { code: silenceMissingPresentationCellScroll(source), map: null };
    }
  },
});

const opaqueFrameLogger = (frontend: string, logger: string): Plugin => ({
  name: "marimo-studio-opaque-frame-logger",
  enforce: "pre",
  resolveId(source, importer) {
    const path = importer?.split("?", 1)[0]?.replaceAll("\\", "/");
    const capabilities = join(frontend, "src", "utils", "capabilities.ts").replaceAll("\\", "/");
    if (source === "./Logger" && path === capabilities) {
      return logger;
    }
  },
});

export const createMarimoViteIntegration = () => {
  const source = readMarimoSourceSync();
  const frontend = join(source.path, "frontend");
  const modules = join(frontend, "node_modules");
  const rtc = join(packageRoot, "src", "server-only-rtc.ts");
  const logger = join(packageRoot, "src", "runtime-logger.ts");
  const languageData = join(packageRoot, "src", "presentation-language-data.ts");
  const radixComposeRefs = join(packageRoot, "src", "radix-compose-refs.ts");
  const wasmWorkers = createWasmWorkerViteIntegration(frontend, packageRoot);

  return {
    plugins: [
      opaqueFrameLogger(frontend, logger),
      evergreenKaTeXFonts(),
      stableDataTableHeaderRefs(),
      quietPresentationCellScroll(),
      ...wasmWorkers.plugins,
    ],
    workerPlugins: wasmWorkers.workerPlugins,
    aliases: [
      {
        find: "@/core/codemirror/rtc/extension",
        replacement: rtc,
      },
      {
        find: "@/utils/Logger",
        replacement: logger,
      },
      {
        find: "@codemirror/language-data",
        replacement: languageData,
      },
      {
        find: "@radix-ui/react-compose-refs",
        replacement: radixComposeRefs,
      },
      {
        find: /^@marimo-team\/frontend\/unstable_internal\/(.*)$/,
        replacement: `${join(frontend, "src")}/$1`,
      },
      {
        find: /^@\/(.*)$/,
        replacement: `${join(frontend, "src")}/$1`,
      },
      {
        find: "@marimo-team/react-slotz",
        replacement: join(modules, "@marimo-team", "react-slotz"),
      },
      // Marimo's exported store, hooks, and providers must share these module
      // instances with the presentation runtime that consumes them.
      {
        find: "react-dom",
        replacement: join(modules, "react-dom"),
      },
      {
        find: "react",
        replacement: join(modules, "react"),
      },
      {
        find: "jotai",
        replacement: join(modules, "jotai"),
      },
      {
        find: "zod",
        replacement: join(modules, "zod"),
      },
    ],
    postcss: join(frontend, "postcss.config.cjs"),
    source,
  };
};
