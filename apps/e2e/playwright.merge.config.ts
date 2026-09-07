import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./",
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }]],
});
