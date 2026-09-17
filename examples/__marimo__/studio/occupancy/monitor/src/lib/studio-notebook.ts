import { parseTemplate } from "@observablehq/notebook-kit";
import { observable } from "@observablehq/notebook-kit/vite";
import { type DefaultTreeAdapterMap, parse } from "parse5";
import type { PluginOption } from "vite";

/** Defer dynamic HTML until Observable can supply complete projection selectors. */
export function studioNotebook(template: string): PluginOption[] {
  const dynamicCells = new Map<string, Set<string>>();
  return [
    observable({
      template,
      transformNotebook(notebook, context) {
        dynamicCells.set(
          context.filename,
          new Set(
            notebook.cells.filter((cell) =>
              cell.mode === "html" &&
              parseTemplate(cell.value).expressions.length > 0
            ).map((cell) => `cell-${cell.id}`),
          ),
        );
        return notebook;
      },
    }),
    {
      name: "studio-notebook-projections",
      transformIndexHtml: {
        order: "pre",
        handler(html, context) {
          const cells = dynamicCells.get(context.filename);
          dynamicCells.delete(context.filename);
          if (!cells?.size) return html;
          const edits: { start: number; end: number }[] = [];
          const visit = (node: DefaultTreeAdapterMap["node"]) => {
            if (
              "tagName" in node && node.tagName === "div" &&
              node.attrs.some(({ name, value }) =>
                name === "id" && cells.has(value)
              )
            ) {
              const location = node.sourceCodeLocation;
              if (location?.startTag && location.endTag) {
                edits.push({
                  start: location.startTag.endOffset,
                  end: location.endTag.startOffset,
                });
                return;
              }
            }
            if ("childNodes" in node) node.childNodes.forEach(visit);
          };
          visit(parse(html, { sourceCodeLocationInfo: true }));
          for (
            const { start, end } of edits.sort((a, b) => b.start - a.start)
          ) {
            html = html.slice(0, start) + html.slice(end);
          }
          return html;
        },
      },
    },
  ];
}
