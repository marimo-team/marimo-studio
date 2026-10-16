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
import { expect, it } from "vite-plus/test";

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
  ["typescript", typescriptLanguage],
  ["typescriptreact", tsxLanguage],
  ["xml", xmlLanguage],
  ["yaml", yamlLanguage],
])("loads the %s CodeMirror language", async (id, expected) => {
  expect(await configuredLanguage(id)).toBe(expected);
});

it.each([
  ["latex", "stex"],
  ["lua", "lua"],
  ["toml", "toml"],
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

it("uses plain text when no workspace language package is available", async () => {
  expect(await configuredLanguage("svelte")).toBeNull();
});

it("caches bounded registry language extensions", async () => {
  expect(await loadSourceLanguage("typescriptreact")).toBe(
    await loadSourceLanguage("typescriptreact"),
  );
});
