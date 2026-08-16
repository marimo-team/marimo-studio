import { defineConfig } from "vite-plus";

import { createMarimoViteIntegration } from "./src/vite.ts";

const marimo = createMarimoViteIntegration();

export default defineConfig({
  resolve: {
    alias: marimo.aliases,
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.mjs"],
    pool: "threads",
  },
});
