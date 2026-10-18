import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vite-plus/test";
import { createMarkdownRenderer } from "vitepress";

import { glossaryLinks, glossaryPage, glossaryTerm, readGlossary } from "../.vitepress/glossary.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const docsRoot = resolve(packageRoot, "../../docs");

const markdownFiles = (directory: string): string[] =>
  readdirSync(directory)
    .sort()
    .flatMap((entry) => {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        return markdownFiles(path);
      }
      return entry.endsWith(".md") ? [path] : [];
    });

describe("glossary", () => {
  it("reads each term's first paragraph as its definition", async () => {
    const md = await createMarkdownRenderer(docsRoot);
    const glossary = readGlossary(
      md,
      [
        "## Views",
        "",
        "### `view.toml` {#view-toml}",
        "",
        "Names the [provider](#view-provider) that builds a **view**.",
        "",
        "A second paragraph for the page only.",
      ].join("\n"),
    );

    expect(glossary).toEqual({
      "view-toml": {
        title: "<code>view.toml</code>",
        definition: "Names the provider that builds a <strong>view</strong>.",
      },
    });
  });

  it("shows a definition card for links to glossary terms", async () => {
    const md = await createMarkdownRenderer(docsRoot);
    md.use(glossaryLinks);
    const html = md.render(
      "A [view](../reference/glossary.md#view) has a [page](./formats.md#html).",
      { relativePath: "guide/example.md" },
    );

    expect(html).toContain('<GlossaryTerm term="view" tip="glossary-tip-1"><a href=');
    expect(html).toContain('aria-describedby="glossary-tip-1"');
    expect(html).toContain("view</a></GlossaryTerm> has");
    expect(html.match(/<GlossaryTerm/g)).toHaveLength(1);
  });

  it("defines every term that the documentation links to", async () => {
    const md = await createMarkdownRenderer(docsRoot);
    const glossary = readGlossary(md, readFileSync(join(docsRoot, glossaryPage), "utf8"));
    const failures = markdownFiles(docsRoot).flatMap((file) => {
      const page = relative(docsRoot, file).replaceAll("\\", "/");
      return md
        .parse(readFileSync(file, "utf8"), {})
        .flatMap((token) => token.children ?? [])
        .filter((token) => token.type === "link_open" && token.attrGet("class") !== "header-anchor")
        .map((token) => glossaryTerm(token.attrGet("href") ?? "", page))
        .filter((term): term is string => term !== undefined && !glossary[term]?.definition)
        .map((term) => `${page}: #${term} has no glossary definition`);
    });

    expect(failures).toEqual([]);
  });
});
