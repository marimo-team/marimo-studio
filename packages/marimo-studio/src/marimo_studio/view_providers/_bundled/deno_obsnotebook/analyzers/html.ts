import { parseTemplate } from "npm:@observablehq/notebook-kit@2.6.4";
import { type DefaultTreeAdapterMap, parse } from "npm:parse5@7.3.0";

export type Element = DefaultTreeAdapterMap["element"];
export type SourceRange = { readonly start: number; readonly end: number };
export type Expression = ReturnType<
  typeof parseTemplate
>["expressions"][number];
export type TemplateExpression = SourceRange & { readonly node: Expression };
export type HtmlSource = {
  readonly text: string;
  readonly offset: number;
  readonly expressions: readonly TemplateExpression[];
};
export type Report = (
  offset: number,
  code: string,
  copy: { message: string; hint?: string },
) => void;

export function* elements(
  node: DefaultTreeAdapterMap["node"],
): Generator<Element> {
  if ("tagName" in node) yield node;
  if ("childNodes" in node) {
    for (const child of node.childNodes) yield* elements(child);
  }
  if ("content" in node) yield* elements(node.content);
}

const inNotebook = (element: Element): boolean => {
  let parent = element.parentNode;
  while (parent) {
    if ("tagName" in parent && parent.tagName === "notebook") return true;
    parent = "parentNode" in parent ? parent.parentNode : null;
  }
  return false;
};

export function* htmlSources(
  source: string,
  report: Report,
): Generator<HtmlSource> {
  const nodes = [...elements(parse(source, { sourceCodeLocationInfo: true }))];
  if (!nodes.some((node) => node.tagName === "notebook")) {
    yield { text: source, offset: 0, expressions: [] };
    return;
  }
  for (const cell of nodes) {
    if (cell.tagName !== "script" || !inNotebook(cell)) continue;
    const location = cell.sourceCodeLocation;
    if (!location?.startTag || !location.endTag) continue;
    const attrs = new Map(cell.attrs.map(({ name, value }) => [name, value]));
    const mode = attrs.get("type");
    const interpreter = [
      "text/x-python",
      "text/x-r",
      "application/vnd.node.javascript",
    ].includes(mode ?? "");
    const database =
      (mode === "application/sql" || mode === "application/sql+view") &&
      !(attrs.get("database") ?? "var:db").startsWith("var:");
    if (interpreter || database) {
      report(location.startOffset, "notebook-build-execution-unsupported", {
        message:
          "Build-time interpreters and database queries are not supported in Studio's contained build.",
        hint:
          "Compute shared data in Marimo and project it with mo-value, or use a local FileAttachment.",
      });
    }
    if (mode !== "text/html") continue;
    const offset = location.startTag.endOffset;
    const text = source.slice(offset, location.endTag.startOffset);
    try {
      const template = parseTemplate(text);
      yield {
        text,
        offset,
        expressions: template.expressions.map((node, index) => ({
          node,
          start: template.quasis[index].end,
          end: template.quasis[index + 1].start,
        })),
      };
    } catch (error) {
      report(offset, "notebook-source-invalid", { message: String(error) });
    }
  }
}

/** Preserve UTF-16 offsets while hiding JavaScript from the HTML parser. */
export const maskExpressions = ({ text, expressions }: HtmlSource): string => {
  const parts: string[] = [];
  let cursor = 0;
  for (const { start, end } of expressions) {
    parts.push(text.slice(cursor, start), "x".repeat(end - start));
    cursor = end;
  }
  parts.push(text.slice(cursor));
  return parts.join("");
};

export const contains = (outer: SourceRange, inner: SourceRange): boolean =>
  outer.start <= inner.start && inner.end <= outer.end;

export const attributeValueRange = (
  source: HtmlSource,
  node: Element,
  name: string,
): SourceRange | undefined => {
  const location = node.sourceCodeLocation?.attrs?.[name];
  if (!location) return;
  const attribute = source.text.slice(location.startOffset, location.endOffset);
  const equals = attribute.indexOf("=");
  if (equals < 0) return;
  const raw = attribute.slice(equals + 1);
  let start = location.startOffset + equals + 1 + raw.length -
    raw.trimStart().length;
  let end = location.endOffset;
  if (source.text[start] === '"' || source.text[start] === "'") {
    start++;
    end--;
  }
  return { start, end };
};
