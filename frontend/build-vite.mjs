import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { createViteConfig } from "./vite.config.ts";

const [root, marimoRepo, htmxPath] = process.argv.slice(2);
if (!root || !marimoRepo || !htmxPath) {
  throw new Error("Expected root, marimo repository, and htmx source paths");
}

const frontend = join(marimoRepo, "frontend");
const [{ build }, { default: topLevelAwait }] = await Promise.all([
  import(
    pathToFileURL(
      join(frontend, "node_modules", "vite", "dist", "node", "index.js"),
    ).href
  ),
  import(
    pathToFileURL(
      join(
        frontend,
        "node_modules",
        "vite-plugin-top-level-await",
        "exports",
        "import.mjs",
      ),
    ).href
  ),
]);

await build(
  createViteConfig({
    root,
    marimoRepo,
    htmxPath,
    plugins: [topLevelAwait()],
  }),
);
