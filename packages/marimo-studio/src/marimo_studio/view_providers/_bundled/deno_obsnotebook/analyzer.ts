import { resolve } from "node:path";
import { parseFragment } from "npm:parse5@7.3.0";

import {
  projectionAttributeMissing,
  projectionKindConflict,
  projectionTargetUnbounded,
  projectionWildcardInvalid,
} from "../_deno/analyzers/projection-diagnostics.ts";
import {
  bounded,
  dynamic,
  type ProjectionKind,
  type StaticResult,
  stringValue,
  targetsFromResult,
} from "../_deno/analyzers/static-values.ts";
import {
  attributeValueRange,
  contains,
  type Element,
  elements,
  type Expression,
  type HtmlSource,
  htmlSources,
  maskExpressions,
  type Report,
} from "./analyzers/html.ts";

type Diagnostic = {
  code: string;
  severity: "error";
  message: string;
  hint?: string;
  path: string;
  line: number;
  column: number;
};
type Site = {
  path: string;
  kind: ProjectionKind;
  allowedTargets: readonly string[] | null;
  line: number;
  column: number;
  offset: number;
};

function evaluateTarget(expression: Expression): StaticResult {
  if (expression.type === "Literal" && typeof expression.value === "string") {
    return bounded(stringValue(expression.value));
  }
  if (expression.type === "ConditionalExpression") {
    const consequent = evaluateTarget(expression.consequent);
    const alternate = evaluateTarget(expression.alternate);
    if (consequent.status === "bounded" && alternate.status === "bounded") {
      return bounded(...consequent.values, ...alternate.values);
    }
  }
  return dynamic();
}

const targetDomain = (
  source: HtmlSource,
  node: Element,
  attribute: string,
  literal: string,
): StaticResult => {
  const location = node.sourceCodeLocation?.startTag;
  if (!location) return dynamic();
  const tag = { start: location.startOffset, end: location.endOffset };
  const values = node.attrs.flatMap(({ name }) => {
    const range = attributeValueRange(source, node, name);
    return range ? [range] : [];
  });
  const expressions = source.expressions.filter((expression) =>
    contains(tag, expression)
  );
  // Expressions outside attribute values are spreads or computed attribute names.
  if (
    expressions.some((expression) =>
      !values.some((value) => contains(value, expression))
    )
  ) return dynamic();
  const value = attributeValueRange(source, node, attribute);
  const selected = value
    ? expressions.filter((expression) => contains(value, expression))
    : [];
  if (selected.length === 0) return bounded(stringValue(literal));
  const expression = selected[0];
  if (
    !value || selected.length !== 1 ||
    source.text.slice(value.start, expression.start).trim() ||
    source.text.slice(expression.end, value.end).trim()
  ) return dynamic();
  return evaluateTarget(expression.node);
};

const [root, ...paths] = Deno.args;
if (!root) throw new Error("Analyzer requires a project root");
const diagnostics: Diagnostic[] = [];
const sites: Site[] = [];
const encoder = new TextEncoder();

for (const path of paths) {
  const text = await Deno.readTextFile(resolve(root, path));
  const point = (offset: number) => {
    const lines = text.slice(0, offset).split(/\r\n|\r|\n/);
    return { path, line: lines.length, column: lines.at(-1)!.length + 1 };
  };
  const report: Report = (offset, code, copy) => {
    diagnostics.push({ code, severity: "error", ...copy, ...point(offset) });
  };
  for (const source of htmlSources(text, report)) {
    const fragment = parseFragment(maskExpressions(source), {
      sourceCodeLocationInfo: true,
      onParseError(error) {
        const inExpression = source.expressions.some(({ start, end }) =>
          start <= error.startOffset && error.startOffset <= end
        );
        if (error.code === "duplicate-attribute" && !inExpression) {
          report(source.offset + error.startOffset, "notebook-html-invalid", {
            message: "HTML attributes must be unique.",
          });
        }
      },
    });
    for (const node of elements(fragment)) {
      const location = node.sourceCodeLocation?.startTag;
      if (!location) continue;
      const attrs = new Map(node.attrs.map(({ name, value }) => [name, value]));
      const offset = source.offset + location.startOffset;
      if (attrs.has("data-marimo-studio-site")) {
        report(offset, "projection-site-reserved", {
          message: "data-marimo-studio-site is reserved for Studio.",
        });
        continue;
      }
      const tag = node.tagName;
      const native = tag === "marimo-cell" || tag === "marimo-output";
      if (!native && !attrs.has("mo-value")) continue;
      if (native && attrs.has("mo-value")) {
        report(offset, "projection-kind-conflict", projectionKindConflict(tag));
        continue;
      }
      const kind = tag === "marimo-cell"
        ? "cell"
        : tag === "marimo-output"
        ? "output"
        : "value";
      const attribute =
        { cell: "name", output: "value", value: "mo-value" }[kind];
      const target = attrs.get(attribute)?.trim();
      const wildcard = attrs.get("data-marimo-allow");
      if (wildcard !== undefined && wildcard !== "*") {
        report(
          offset,
          "projection-wildcard-invalid",
          projectionWildcardInvalid(),
        );
        continue;
      }
      if (!target) {
        report(
          offset,
          "projection-target-missing",
          projectionAttributeMissing(kind),
        );
        continue;
      }
      const targets = wildcard === "*" ? null : targetsFromResult(
        kind,
        targetDomain(source, node, attribute, target),
      );
      if (targets !== null && "status" in targets) {
        if (targets.status === "invalid") {
          report(offset, targets.code, { message: targets.message });
        } else {
          report(offset, "projection-target-unbounded", {
            ...projectionTargetUnbounded(kind),
            hint:
              'Use a literal selector or a conditional with literal targets. Add data-marimo-allow="*" for runtime selectors or attribute spreads.',
          });
        }
        continue;
      }
      sites.push({
        ...point(offset),
        kind,
        allowedTargets: targets,
        offset: encoder.encode(text.slice(0, offset + 1 + tag.length)).length,
      });
    }
  }
}

console.log(JSON.stringify({ schema: 1, sites, diagnostics }));
