import { access } from "node:fs/promises";

import { documentationExampleFamilies } from "../examples.ts";
import { documentationServerArguments } from "./server-arguments.ts";

const serverArguments = documentationServerArguments(process.argv.slice(2), process.env.PORT);

// The dev server serves whatever examples are already exported. VitePress picks up
// exports published while it runs, so the examples build never blocks serving.
if (serverArguments[0] === "dev") {
  const examples = new URL("../public/examples/", import.meta.url);
  const targets = documentationExampleFamilies.flatMap((family) =>
    ["notebook", ...family.views.map((view) => view.key)].map(
      (target) => `${family.slug}/${target}`,
    ),
  );
  const missing: string[] = [];
  for (const target of targets) {
    try {
      await access(new URL(`${target}/index.html`, examples));
    } catch {
      missing.push(target);
    }
  }
  if (missing.length > 0) {
    console.warn(
      `${missing.length} of ${targets.length} example exports are missing: ${missing.join(", ")}.\n` +
        "Export them with `make docs-examples` while the server runs, or one family with " +
        "`make docs-examples EXAMPLES='--family SLUG'`, then reload the page.",
    );
  }
}

process.argv.splice(2, process.argv.length, ...serverArguments);
const cli = import.meta.resolve("vitepress/dist/node/cli.js");
await import(cli);
