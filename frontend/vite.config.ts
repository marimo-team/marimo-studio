import { join } from "node:path";

import { resolveOwnedDependency } from "./upstream-dependency.ts";

interface BuildOptions {
  root: string;
  marimoRepo: string;
  htmxPath: string;
  plugins: unknown[];
}

export const createViteConfig = (options: BuildOptions) => {
  const frontend = join(options.marimoRepo, "frontend");
  const modules = join(frontend, "node_modules");
  const htmlLanguage = resolveOwnedDependency(
    frontend,
    "@uiw/codemirror-extensions-langs",
    "@codemirror/lang-html",
  );
  const cssLanguage = resolveOwnedDependency(
    frontend,
    "@uiw/codemirror-extensions-langs",
    "@codemirror/lang-css",
  );
  const bridge = join(
    options.root,
    "frontend",
    "src",
    "marimo-adapter",
    "server-only-bridge.ts",
  );
  const rtc = join(
    options.root,
    "frontend",
    "src",
    "marimo-adapter",
    "server-only-rtc.ts",
  );
  return {
    base: "./",
    root: join(options.root, "frontend"),
    css: {
      postcss: join(frontend, "postcss.config.cjs"),
    },
    plugins: [
      {
        name: "marimo-studio-server-runtime",
        enforce: "pre",
        resolveId(source: string, importer?: string) {
          if (
            source === "../wasm/bridge" &&
            importer?.endsWith("/core/websocket/useWebSocket.tsx")
          ) {
            return bridge;
          }
          return null;
        },
      },
      ...options.plugins,
    ],
    resolve: {
      alias: [
        {
          find: join(frontend, "src", "core", "wasm", "bridge.ts"),
          replacement: bridge,
        },
        {
          find: "@/core/codemirror/rtc/extension",
          replacement: rtc,
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
          find: "htmx.org",
          replacement: options.htmxPath,
        },
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
          find: "@uiw/react-codemirror",
          replacement: join(modules, "@uiw", "react-codemirror"),
        },
        {
          find: "@codemirror/lang-html",
          replacement: htmlLanguage,
        },
        {
          find: "@codemirror/lang-css",
          replacement: cssLanguage,
        },
      ],
    },
    build: {
      outDir: join(
        options.root,
        "src",
        "marimo_studio",
        "_static",
        "server-runtime",
      ),
      emptyOutDir: true,
      cssCodeSplit: false,
      rollupOptions: {
        input: {
          runtime: join(options.root, "frontend", "src", "main.ts"),
          "dev-reload": join(
            options.root,
            "frontend",
            "src",
            "dev-reload.ts",
          ),
          studio: join(options.root, "frontend", "src", "studio.ts"),
        },
        output: {
          entryFileNames: "[name].js",
          chunkFileNames: "chunks/[name]-[hash].js",
          assetFileNames(assetInfo: { names?: string[] }) {
            if (assetInfo.names?.some((name) => name.endsWith(".css"))) {
              return "runtime.css";
            }
            return "assets/[name]-[hash][extname]";
          },
        },
      },
    },
  };
};
