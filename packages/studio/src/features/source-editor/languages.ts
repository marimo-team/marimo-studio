import type { Extension } from "@codemirror/state";

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
  [
    "typescript",
    async () => (await import("@codemirror/lang-javascript")).javascript({ typescript: true }),
  ],
  [
    "typescriptreact",
    async () =>
      (await import("@codemirror/lang-javascript")).javascript({ jsx: true, typescript: true }),
  ],
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
