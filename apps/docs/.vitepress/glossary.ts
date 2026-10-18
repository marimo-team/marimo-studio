import type { MarkdownRenderer } from "vitepress";

import { posix } from "node:path";

type CoreRule = Parameters<MarkdownRenderer["core"]["ruler"]["push"]>[1];
type CoreState = Parameters<CoreRule>[0];
type Token = CoreState["tokens"][number];

export interface GlossaryEntry {
  title: string;
  definition: string;
}

export type Glossary = Record<string, GlossaryEntry>;

export const glossaryPage = "reference/glossary.md";

const escapeHtml = (text: string): string =>
  text.replace(/[&<>"]/g, (character) => `&#${character.charCodeAt(0)};`);

/** Returns the glossary term that `href` links to from `page`, if any. */
export const glossaryTerm = (href: string, page: string): string | undefined => {
  const [path = "", fragment] = href.split("#", 2);
  if (!fragment || /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(path)) {
    return undefined;
  }
  const resolved = path.startsWith("/")
    ? path.slice(1)
    : posix.join(posix.dirname(page), path || posix.basename(page));
  const file = resolved.endsWith(".md") ? resolved : `${resolved}.md`;
  return file === glossaryPage ? decodeURIComponent(fragment) : undefined;
};

// Hover cards hold text only, so links collapse to their label and heading
// permalinks disappear.
const inlineHtml = (tokens: readonly Token[]): string => {
  let html = "";
  let permalink = false;
  for (const token of tokens) {
    if (token.type === "link_open") {
      permalink = token.attrGet("class") === "header-anchor";
    } else if (token.type === "link_close") {
      permalink = false;
    } else if (permalink) {
      continue;
    } else if (token.type === "text") {
      html += escapeHtml(token.content);
    } else if (token.type === "code_inline") {
      html += `<code>${escapeHtml(token.content)}</code>`;
    } else if (/^(?:strong|em)_(?:open|close)$/.test(token.type)) {
      html += `<${token.nesting === -1 ? "/" : ""}${token.tag}>`;
    } else if (token.type === "softbreak" || token.type === "hardbreak") {
      html += " ";
    }
  }
  return html.trim();
};

/**
 * Reads the glossary page into definitions keyed by heading ID.
 *
 * Each `###` heading is a term, and the paragraph right after it is the
 * definition that hover cards show.
 */
export const readGlossary = (md: MarkdownRenderer, source: string): Glossary => {
  const tokens = md.parse(source, {});
  const glossary: Glossary = {};
  tokens.forEach((token, index) => {
    const id = token.attrGet("id");
    if (token.type !== "heading_open" || token.tag !== "h3" || !id) {
      return;
    }
    const paragraph = tokens[index + 3];
    const definition = tokens[index + 4];
    glossary[id] = {
      title: inlineHtml(tokens[index + 1]?.children ?? []),
      definition:
        paragraph?.type === "paragraph_open" ? inlineHtml(definition?.children ?? []) : "",
    };
  });
  return glossary;
};

/**
 * Wraps each Markdown link to a glossary term in `<GlossaryTerm>`, which shows
 * the term's definition while the link is hovered or focused.
 */
export const glossaryLinks = (md: MarkdownRenderer): void => {
  md.core.ruler.push("glossary_links", (state) => {
    const page: string = state.env?.relativePath ?? "";
    state.tokens.forEach((block, index) => {
      // Heading text feeds the page outline, so headings keep plain links.
      if (block.type !== "inline" || state.tokens[index - 1]?.type === "heading_open") {
        return;
      }
      const children: Token[] = [];
      let open = false;
      for (const token of block.children ?? []) {
        const term =
          token.type === "link_open" && token.attrGet("class") !== "header-anchor"
            ? glossaryTerm(token.attrGet("href") ?? "", page)
            : undefined;
        if (term) {
          state.env.glossaryTips = (state.env.glossaryTips ?? 0) + 1;
          const tip = `glossary-tip-${state.env.glossaryTips}`;
          const wrapper = new state.Token("html_inline", "", 0);
          wrapper.content = `<GlossaryTerm term="${escapeHtml(term)}" tip="${tip}">`;
          token.attrSet("aria-describedby", tip);
          children.push(wrapper, token);
          open = true;
        } else if (token.type === "link_close" && open) {
          const wrapper = new state.Token("html_inline", "", 0);
          wrapper.content = "</GlossaryTerm>";
          children.push(token, wrapper);
          open = false;
        } else {
          children.push(token);
        }
      }
      block.children = children;
    });
  });
};
