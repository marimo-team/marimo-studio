import { createMarimoViteIntegration } from "@marimo-studio/marimo-frontend/vite";
import { defineConfig } from "vite-plus";

const marimo = createMarimoViteIntegration();
const contracts = [
  "tests/retry.test.ts",
  "tests/cell-state.test.ts",
  "tests/cell-output-policy.test.ts",
  "tests/value-state.test.ts",
  "tests/output-read-batcher.test.ts",
];

export default defineConfig({
  plugins: marimo.plugins,
  resolve: {
    alias: marimo.aliases,
  },
  test: {
    pool: "threads",
    projects: [
      {
        extends: true,
        test: { name: "presentation-contracts", environment: "node", include: contracts },
      },
      {
        extends: true,
        test: {
          name: "presentation-dom",
          environment: "jsdom",
          include: ["tests/**/*.test.ts"],
          exclude: contracts,
        },
      },
    ],
  },
});
