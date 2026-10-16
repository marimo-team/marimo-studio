import type { Extension } from "@codemirror/state";

import { StreamLanguage } from "@codemirror/language";

type LanguageLoader = () => Promise<Extension>;

const PLAIN_TEXT_EXTENSION: Extension = [];

const languageLoaders = new Map<string, LanguageLoader>([
  ["css", async () => (await import("@codemirror/lang-css")).css()],
  ["html", async () => (await import("@codemirror/lang-html")).html()],
  ["javascript", async () => (await import("@codemirror/lang-javascript")).javascript()],
  [
    "javascriptreact",
    async () => (await import("@codemirror/lang-javascript")).javascript({ jsx: true }),
  ],
  ["json", async () => (await import("@codemirror/lang-json")).json()],
  [
    "latex",
    async () => StreamLanguage.define((await import("@codemirror/legacy-modes/mode/stex")).stex),
  ],
  [
    "lua",
    async () => StreamLanguage.define((await import("@codemirror/legacy-modes/mode/lua")).lua),
  ],
  [
    "markdown",
    async () => {
      const [{ markdown }, { yamlFrontmatter }] = await Promise.all([
        import("@codemirror/lang-markdown"),
        import("@codemirror/lang-yaml"),
      ]);
      return yamlFrontmatter({ content: markdown() });
    },
  ],
  ["python", async () => (await import("@codemirror/lang-python")).python()],
  ["scss", async () => (await import("@codemirror/lang-sass")).sass()],
  [
    "toml",
    async () => StreamLanguage.define((await import("@codemirror/legacy-modes/mode/toml")).toml),
  ],
  [
    "typescript",
    async () => (await import("@codemirror/lang-javascript")).javascript({ typescript: true }),
  ],
  [
    "typescriptreact",
    async () =>
      (await import("@codemirror/lang-javascript")).javascript({ jsx: true, typescript: true }),
  ],
  ["xml", async () => (await import("@codemirror/lang-xml")).xml()],
  ["yaml", async () => (await import("@codemirror/lang-yaml")).yaml()],
]);

const loadedLanguages = new Map<string, Promise<Extension>>();

export const plainTextSourceLanguage = (): Extension => PLAIN_TEXT_EXTENSION;

export const loadSourceLanguage = (language: string): Promise<Extension> => {
  const loader = languageLoaders.get(language);
  if (!loader) {
    return Promise.resolve(PLAIN_TEXT_EXTENSION);
  }
  const loaded = loadedLanguages.get(language) ?? loader().catch(() => PLAIN_TEXT_EXTENSION);
  loadedLanguages.set(language, loaded);
  return loaded;
};
