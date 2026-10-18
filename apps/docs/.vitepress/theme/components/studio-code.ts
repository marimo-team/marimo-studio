export type TokenKind =
  | "plain"
  | "keyword"
  | "string"
  | "number"
  | "function"
  | "comment"
  | "decorator"
  | "tag"
  | "attribute";

export interface Token {
  text: string;
  kind: TokenKind;
}

const pythonKeywords = new Set([
  "and",
  "def",
  "False",
  "for",
  "if",
  "import",
  "in",
  "None",
  "not",
  "or",
  "return",
  "True",
]);

const pythonPattern =
  /(#[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(@[\w.]+)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(?=\()|([A-Za-z_]\w*)/g;

/**
 * Splits a short, authored Python snippet into tokens for marimo's editor
 * colors. Figures show fixed snippets, so a pattern tokenizer is enough.
 */
export const pythonTokens = (source: string): Token[] => {
  const tokens: Token[] = [];
  let last = 0;
  for (const match of source.matchAll(pythonPattern)) {
    const index = match.index ?? 0;
    if (index > last) {
      tokens.push({ text: source.slice(last, index), kind: "plain" });
    }
    const [text, comment, string, decorator, number, call, name] = match;
    let kind: TokenKind = "plain";
    if (comment) {
      kind = "comment";
    } else if (string) {
      kind = "string";
    } else if (decorator) {
      kind = "decorator";
    } else if (number) {
      kind = "number";
    } else if (pythonKeywords.has(call ?? name ?? "")) {
      kind = "keyword";
    } else if (call) {
      kind = "function";
    }
    tokens.push({ text, kind });
    last = index + text.length;
  }
  if (last < source.length) {
    tokens.push({ text: source.slice(last), kind: "plain" });
  }
  return tokens;
};

const markupPattern = /(<\/?[\w-]+)|([\w-]+)(?==)|("[^"]*")|(\/?>)/g;

/** Splits a short HTML snippet into tag, attribute, and string tokens. */
export const markupTokens = (source: string): Token[] => {
  const tokens: Token[] = [];
  let last = 0;
  for (const match of source.matchAll(markupPattern)) {
    const index = match.index ?? 0;
    if (index > last) {
      tokens.push({ text: source.slice(last, index), kind: "plain" });
    }
    const [text, , attribute, string] = match;
    let kind: TokenKind = "tag";
    if (attribute) {
      kind = "attribute";
    } else if (string) {
      kind = "string";
    }
    tokens.push({ text, kind });
    last = index + text.length;
  }
  if (last < source.length) {
    tokens.push({ text: source.slice(last), kind: "plain" });
  }
  return tokens;
};

const yamlPattern = /(#[^\n]*)|([\w-]+)(?=:)|("[^"]*")|(\b\d+(?:\.\d+)?\b)/g;

/** Splits a short YAML snippet into key, string, and number tokens. */
export const yamlTokens = (source: string): Token[] => {
  const tokens: Token[] = [];
  let last = 0;
  for (const match of source.matchAll(yamlPattern)) {
    const index = match.index ?? 0;
    if (index > last) {
      tokens.push({ text: source.slice(last, index), kind: "plain" });
    }
    const [text, comment, key, string] = match;
    let kind: TokenKind = "number";
    if (comment) {
      kind = "comment";
    } else if (key) {
      kind = "attribute";
    } else if (string) {
      kind = "string";
    }
    tokens.push({ text, kind });
    last = index + text.length;
  }
  if (last < source.length) {
    tokens.push({ text: source.slice(last), kind: "plain" });
  }
  return tokens;
};

export type CodeLanguage = "python" | "html" | "yaml";

const tokenizers: Record<CodeLanguage, (source: string) => Token[]> = {
  python: pythonTokens,
  html: markupTokens,
  yaml: yamlTokens,
};

/** Tokenizes `source` line by line, so figures can mark individual lines. */
export const codeLines = (source: string, language: CodeLanguage): Token[][] =>
  source.split("\n").map((line) => tokenizers[language](line));
