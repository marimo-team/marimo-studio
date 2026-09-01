import { createMarimoViteIntegration } from "@marimo-studio/marimo-frontend/vite";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite-plus";

import { buildMetadata } from "./build-metadata.ts";
import { browserLicenseInventory } from "./license-inventory.ts";

const packageRoot = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = resolve(packageRoot, "../..");
const marimo = createMarimoViteIntegration();
const licenses = browserLicenseInventory();
const entrypoint = (specifier: string) => fileURLToPath(import.meta.resolve(specifier));

export default defineConfig({
  base: "./",
  css: {
    postcss: marimo.postcss,
  },
  plugins: [...marimo.plugins, buildMetadata(), licenses.emitter],
  worker: {
    plugins: () => [...marimo.workerPlugins(), licenses.collector()],
  },
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
    emptyOutDir: true,
    cssCodeSplit: true,
    manifest: "entry-manifest.json",
    rollupOptions: {
      input: {
        runtime: join(packageRoot, "src", "runtime.ts"),
        "dev-reload": entrypoint("@marimo-studio/presentation/dev-reload"),
        studio: join(packageRoot, "src", "studio.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames(assetInfo) {
          if (assetInfo.names.some((name) => name.endsWith(".css"))) {
            return "[name][extname]";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
