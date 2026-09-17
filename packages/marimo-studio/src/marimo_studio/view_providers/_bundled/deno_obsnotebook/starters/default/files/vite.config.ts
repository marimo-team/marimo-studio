import { config } from "@observablehq/notebook-kit/vite";
import { defineConfig, mergeConfig } from "vite";

import { studioNotebook } from "./src/lib/studio-notebook.ts";

export default defineConfig(mergeConfig(config(), {
  plugins: [studioNotebook("src/page.tmpl")],
  resolve: { alias: { "https://cdn.jsdelivr.net/npm/htl/+esm": "htl" } },
  server: { host: "127.0.0.1" },
  css: { postcss: {} },
}));
