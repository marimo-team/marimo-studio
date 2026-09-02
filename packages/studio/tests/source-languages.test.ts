import { cssLanguage } from "@codemirror/lang-css";
import { htmlLanguage } from "@codemirror/lang-html";
import {
  javascriptLanguage,
  jsxLanguage,
  tsxLanguage,
  typescriptLanguage,
} from "@codemirror/lang-javascript";
import { language, type Language } from "@codemirror/language";
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
  ["typescript", typescriptLanguage],
  ["typescriptreact", tsxLanguage],
])("loads the %s CodeMirror language", async (id, expected) => {
  expect(await configuredLanguage(id)).toBe(expected);
});

it("uses plain text when no workspace language package is available", async () => {
  expect(await configuredLanguage("svelte")).toBeNull();
});

it("caches bounded registry language extensions", async () => {
  expect(await loadSourceLanguage("typescriptreact")).toBe(
    await loadSourceLanguage("typescriptreact"),
  );
});
