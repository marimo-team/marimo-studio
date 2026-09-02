import { defineConfig } from "vite-plus";

import { createMarimoViteIntegration } from "./src/vite.ts";

const marimo = createMarimoViteIntegration();

export default defineConfig({
  plugins: marimo.plugins,
  resolve: {
    alias: marimo.aliases,
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx", "tests/**/*.test.mjs"],
    pool: "threads",
  },
});
