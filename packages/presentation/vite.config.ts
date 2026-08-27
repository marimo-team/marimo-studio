import { createMarimoViteIntegration } from "@marimo-studio/marimo-frontend/vite";
import { defineConfig } from "vite-plus";

const marimo = createMarimoViteIntegration();

export default defineConfig({
  plugins: marimo.plugins,
  resolve: {
    alias: marimo.aliases,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    pool: "threads",
  },
});
