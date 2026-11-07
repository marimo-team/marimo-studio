import type { StreamParser } from "@codemirror/language";

interface BibtexState {
  /** Brace depth: 0 between entries, 1 among an entry's fields, 2+ in a value. */
  depth: number;
  quoted: boolean;
}

// BibTeX ignores text between entries, so it reads as a comment. Field values
// in braces or quotes may span lines and hold `%`, as URLs often do.
export const bibtex: StreamParser<BibtexState> = {
  name: "bibtex",
  startState: () => ({ depth: 0, quoted: false }),
  copyState: (state) => ({ ...state }),
  token(stream, state) {
    if (state.quoted) {
      while (!stream.eol()) {
        const char = stream.next();
        if (char === "\\") {
          stream.next();
        } else if (char === '"') {
          state.quoted = false;
          break;
        }
      }
      return "string";
    }
    if (state.depth >= 2) {
      while (!stream.eol()) {
        const char = stream.next();
        if (char === "\\") {
          stream.next();
        } else if (char === "{") {
          state.depth += 1;
        } else if (char === "}" && --state.depth === 1) {
          break;
        }
      }
      return "string";
    }
    if (stream.eatSpace()) {
      return null;
    }
    if (state.depth === 0) {
      if (stream.match(/^@[A-Za-z]+/)) {
        return "keyword";
      }
      if (stream.eat("{") || stream.eat("(")) {
        state.depth = 1;
        return "bracket";
      }
      if (!stream.skipTo("@")) {
        stream.skipToEnd();
      }
      return "comment";
    }
    if (stream.eat("{")) {
      state.depth = 2;
      return "string";
    }
    if (stream.eat("}") || stream.eat(")")) {
      state.depth = 0;
      return "bracket";
    }
    if (stream.eat('"')) {
      state.quoted = true;
      return "string";
    }
    if (stream.match(/^[A-Za-z][\w:.+-]*(?=\s*=)/)) {
      return "propertyName";
    }
    if (stream.match(/^\d+(?![\w:.+-])/)) {
      return "number";
    }
    if (stream.match(/^[=#,]/)) {
      return "operator";
    }
    if (!stream.match(/^[^\s=#,{}()"]+/)) {
      stream.next();
    }
    return "variableName";
  },
  languageData: { commentTokens: { line: "%" } },
};
