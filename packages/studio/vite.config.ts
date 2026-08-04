import { defineConfig } from "vite-plus";

export default defineConfig({
  test: {
    environment: "jsdom",
    pool: "threads",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
