import { createMarimoViteIntegration } from "@marimo-studio/marimo-frontend/vite";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite-plus";

import { entryClosures } from "./entry-closures.ts";

const packageRoot = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = resolve(packageRoot, "../..");
const marimo = createMarimoViteIntegration();

export default defineConfig({
  base: "./",
  css: {
    postcss: marimo.postcss,
  },
  plugins: [
    entryClosures({
      entries: ["zero-python"],
      fileName: "entry-closures.zero-python.json",
    }),
  ],
  resolve: {
    alias: marimo.aliases,
  },
  build: {
    outDir: join(
      workspaceRoot,
      "packages",
      "marimo-studio",
      "src",
      "marimo_studio",
      "_static",
      "browser",
    ),
    emptyOutDir: false,
    cssCodeSplit: true,
    rollupOptions: {
      input: {
        "zero-python": join(packageRoot, "src", "zero-python.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "zero-python/chunks/[name]-[hash].js",
        assetFileNames(assetInfo) {
          if (assetInfo.names.some((name) => name.endsWith(".css"))) {
            return "zero-python/[name][extname]";
          }
          return "zero-python/assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
