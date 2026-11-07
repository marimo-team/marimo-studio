import { cssLanguage } from "@codemirror/lang-css";
import { htmlLanguage } from "@codemirror/lang-html";
import {
  javascriptLanguage,
  jsxLanguage,
  tsxLanguage,
  typescriptLanguage,
} from "@codemirror/lang-javascript";
import { jsonLanguage } from "@codemirror/lang-json";
import { pythonLanguage } from "@codemirror/lang-python";
import { sassLanguage } from "@codemirror/lang-sass";
import { xmlLanguage } from "@codemirror/lang-xml";
import { yamlLanguage } from "@codemirror/lang-yaml";
import { ensureSyntaxTree, language, type Language } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { svelteLanguage } from "@replit/codemirror-lang-svelte";
import { readFileSync } from "node:fs";
import { expect, it } from "vite-plus/test";
import { z } from "zod";

import { loadSourceLanguage } from "../src/features/source-editor/languages.ts";

const configuredLanguage = async (id: string): Promise<Language | null> => {
  const extension = await loadSourceLanguage(id);
  return EditorState.create({ doc: "const value = 1", extensions: [extension] }).facet(language);
};

it.each([
  ["css", cssLanguage],
  ["html", htmlLanguage],
  ["javascript", javascriptLanguage],
  ["javascriptreact", jsxLanguage],
  ["json", jsonLanguage],
  ["python", pythonLanguage],
  ["scss", sassLanguage],
  ["svelte", svelteLanguage],
  ["typescript", typescriptLanguage],
  ["typescriptreact", tsxLanguage],
  ["xml", xmlLanguage],
  ["yaml", yamlLanguage],
])("loads the %s CodeMirror language", async (id, expected) => {
  expect(await configuredLanguage(id)).toBe(expected);
});

it.each([
  ["bibtex", "bibtex"],
  ["latex", "stex"],
  ["lua", "lua"],
  ["toml", "toml"],
  ["typst", "typst"],
])("loads the %s CodeMirror language as %s", async (id, name) => {
  expect((await configuredLanguage(id))?.name).toBe(name);
});

it("parses Markdown front matter as YAML", async () => {
  const doc = "---\ntitle: Paper\n---\n\n# Results\n";
  const state = EditorState.create({ doc, extensions: [await loadSourceLanguage("markdown")] });
  const tree = ensureSyntaxTree(state, doc.length, 5000);
  const ancestors = (text: string): string[] => {
    const names = [];
    for (let node = tree?.resolveInner(doc.indexOf(text), 1) ?? null; node; node = node.parent) {
      names.push(node.name);
    }
    return names;
  };

  expect(ancestors("title")).toContain("Pair");
  expect(ancestors("Results")).toContain("ATXHeading1");
});

it("reads BibTeX field values in braces and quotes as strings", async () => {
  const doc = [
    "Text between entries, mailed to someone@ example.org @",
    "@article{smith2020deep,",
    "  % Checked against the DOI.",
    "  url = {https://example.org/paper%20one.pdf},",
    '  title = "Deep {Learning}",',
    "  year = 2020,",
    "}",
  ].join("\n");
  const state = EditorState.create({ doc, extensions: [await loadSourceLanguage("bibtex")] });
  const tree = ensureSyntaxTree(state, doc.length, 5000);
  const tokenAt = (text: string): string | undefined =>
    tree?.resolveInner(doc.indexOf(text) + 1, 1).name;

  expect(tokenAt("Text between")).toBe("comment");
  expect(tokenAt("@ example")).toBe("comment");
  expect(tokenAt("% Checked")).toBe("comment");
  expect(tokenAt("@article")).toBe("keyword");
  expect(tokenAt("smith2020deep")).toBe("variableName");
  expect(tokenAt("url")).toBe("propertyName");
  expect(tokenAt("%20one")).toBe("string");
  expect(tokenAt("Learning")).toBe("string");
  expect(tokenAt("2020,")).toBe("number");
});

// Studio's provider tests keep this fixture equal to the languages that
// built-in providers report.
const { languages: reportedLanguages } = z
  .object({ languages: z.array(z.string()) })
  .parse(
    JSON.parse(
      readFileSync(
        new URL("../../protocol/fixtures/source-languages.json", import.meta.url),
        "utf8",
      ),
    ),
  );

it.each(reportedLanguages.filter((id) => id !== "plaintext"))(
  "loads a CodeMirror language for the reported %s documents",
  async (id) => {
    expect(await configuredLanguage(id)).not.toBeNull();
  },
);

it.each(["plaintext", "unknown"])("shows %s documents as plain text", async (id) => {
  expect(await configuredLanguage(id)).toBeNull();
});

it("caches bounded registry language extensions", async () => {
  expect(await loadSourceLanguage("typescriptreact")).toBe(
    await loadSourceLanguage("typescriptreact"),
  );
});
