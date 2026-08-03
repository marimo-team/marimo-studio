import { createMarimoViteIntegration } from "@marimo-studio/marimo-frontend/vite";
import { defineConfig } from "vite-plus";

const marimo = createMarimoViteIntegration();

export default defineConfig({
  resolve: {
    alias: marimo.aliases,
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
