import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createMarkdownRenderer, defineLoader } from "vitepress";

import { type Glossary, readGlossary } from "../glossary.ts";

declare const data: Glossary;
export { data };

const docsRoot = fileURLToPath(new URL("../../../../docs/", import.meta.url));

export default defineLoader({
  watch: ["../../../../docs/reference/glossary.md"],
  async load([file]): Promise<Glossary> {
    const md = await createMarkdownRenderer(docsRoot);
    return readGlossary(md, readFileSync(file ?? "", "utf8"));
  },
});
