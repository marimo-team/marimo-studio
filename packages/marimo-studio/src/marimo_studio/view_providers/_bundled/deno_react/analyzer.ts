import { resolve } from "node:path";
import ts from "npm:typescript@6.0.3";

import {
  arrayItems,
  type ProjectionKind,
  propertyValues,
  type StaticResult,
  targetsFromResult,
} from "../_deno/analyzers/static-values.ts";
import {
  projectionAttributeDuplicate,
  projectionAttributeMissing,
  projectionKindConflict,
  projectionTargetUnbounded,
  projectionUsageHint,
  projectionWildcardInvalid,
} from "../_deno/analyzers/projection-diagnostics.ts";
import { TypeScriptModules } from "../_deno/analyzers/typescript-modules.ts";
import {
  evaluateTypeScript,
  type TypeScriptScope,
} from "../_deno/analyzers/typescript-values.ts";

type Diagnostic = {
  readonly code: string;
  readonly severity: "error" | "warning";
  readonly message: string;
  readonly path?: string;
  readonly line?: number;
  readonly column?: number;
  readonly hint?: string;
};

type Site = {
  readonly path: string;
  readonly kind: ProjectionKind;
  readonly allowedTargets: readonly string[] | null;
  readonly line: number;
  readonly column: number;
  readonly offset: number;
};

const [root, ...files] = Deno.args;
if (!root) throw new Error("Analyzer requires a project root");

const sites: Site[] = [];
const diagnostics: Diagnostic[] = [];
const encoder = new TextEncoder();
const modules = new TypeScriptModules(root);

const sourcePoint = (
  source: ts.SourceFile,
  node: ts.Node,
): { line: number; column: number } => {
  const point = source.getLineAndCharacterOfPosition(node.getStart(source));
  return { line: point.line + 1, column: point.character + 1 };
};

const moduleTarget = (node: ts.Node): string | null => {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    return node.text;
  }
  return null;
};

const moduleNode = (node: ts.Node): ts.Node | undefined => {
  if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
    return node.moduleSpecifier;
  }
  if (
    ts.isImportEqualsDeclaration(node) &&
    ts.isExternalModuleReference(node.moduleReference)
  ) {
    return node.moduleReference.expression;
  }
  if (
    ts.isCallExpression(node) &&
    (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
      (ts.isIdentifier(node.expression) && node.expression.text === "require"))
  ) {
    return node.arguments[0];
  }
  return undefined;
};

for (const path of files) {
  try {
    modules.add(path, await Deno.readTextFile(resolve(root, path)));
  } catch (error) {
    diagnostics.push({
      code: "source-read-failed",
      severity: "error",
      message: error instanceof Error ? error.message : String(error),
      path,
    });
  }
}

const bindPattern = (
  pattern: ts.BindingName,
  values: StaticResult,
  scope: Map<string, StaticResult>,
): void => {
  if (ts.isIdentifier(pattern)) {
    scope.set(pattern.text, values);
    return;
  }
  if (ts.isObjectBindingPattern(pattern)) {
    for (const element of pattern.elements) {
      if (!ts.isIdentifier(element.name)) continue;
      const property = element.propertyName !== undefined &&
          (ts.isIdentifier(element.propertyName) ||
            ts.isStringLiteral(element.propertyName))
        ? element.propertyName.text
        : element.name.text;
      scope.set(element.name.text, propertyValues(values, property));
    }
  }
};

const expressionScope = (
  node: ts.Node,
  source: ts.SourceFile,
): TypeScriptScope => {
  const callbacks: (ts.ArrowFunction | ts.FunctionExpression)[] = [];
  let current: ts.Node | undefined = node;
  while (current !== undefined) {
    if (
      (ts.isArrowFunction(current) || ts.isFunctionExpression(current)) &&
      ts.isCallExpression(current.parent) &&
      current.parent.arguments.includes(current) &&
      ts.isPropertyAccessExpression(current.parent.expression) &&
      current.parent.expression.name.text === "map"
    ) {
      callbacks.push(current);
    }
    current = current.parent;
  }
  const scope = new Map<string, StaticResult>();
  for (const callback of callbacks.reverse()) {
    const call = callback.parent as ts.CallExpression;
    const receiver =
      (call.expression as ts.PropertyAccessExpression).expression;
    const values = arrayItems(
      evaluateTypeScript(receiver, source, modules, scope),
    );
    const parameter = callback.parameters[0];
    if (parameter !== undefined) bindPattern(parameter.name, values, scope);
  }
  return scope;
};

const attributes = (
  opening: ts.JsxOpeningLikeElement,
  name: string,
): ts.JsxAttribute[] =>
  opening.attributes.properties.filter(
    (item): item is ts.JsxAttribute =>
      ts.isJsxAttribute(item) && item.name.getText() === name,
  );

const literal = (item: ts.JsxAttribute): string | null => {
  const initializer = item.initializer;
  if (initializer === undefined) return null;
  if (ts.isStringLiteral(initializer)) return initializer.text.trim();
  if (
    !ts.isJsxExpression(initializer) || initializer.expression === undefined
  ) return null;
  const expression = initializer.expression;
  return ts.isStringLiteral(expression) ||
      ts.isNoSubstitutionTemplateLiteral(expression)
    ? expression.text.trim()
    : null;
};

const openingOffset = (
  source: ts.SourceFile,
  opening: ts.JsxOpeningLikeElement,
): number => {
  const end = opening.end;
  const characterOffset = source.text.slice(end - 2, end) === "/>"
    ? end - 2
    : end - 1;
  return encoder.encode(source.text.slice(0, characterOffset)).length;
};

const reportTarget = (
  path: string,
  source: ts.SourceFile,
  opening: ts.JsxOpeningLikeElement,
  kind: ProjectionKind,
  attributeName: string,
): void => {
  const point = sourcePoint(source, opening);
  const wildcardAttributes = attributes(opening, "data-marimo-allow");
  const allowsWildcard = wildcardAttributes.length === 1 &&
    literal(wildcardAttributes[0]) === "*";
  if (
    wildcardAttributes.length > 1 ||
    (wildcardAttributes.length === 1 && !allowsWildcard)
  ) {
    const diagnostic = projectionWildcardInvalid();
    diagnostics.push({
      code: "projection-wildcard-invalid",
      severity: "error",
      ...diagnostic,
      path,
      ...point,
    });
    return;
  }
  const matches = attributes(opening, attributeName);
  if (matches.length > 1) {
    const diagnostic = projectionAttributeDuplicate(kind);
    diagnostics.push({
      code: "projection-target-duplicate",
      severity: "error",
      ...diagnostic,
      path,
      ...point,
    });
    return;
  }
  const targetAttribute = matches[0];
  const properties = opening.attributes.properties;
  const spreadCanProvideTarget = properties.some(ts.isJsxSpreadAttribute);
  if (targetAttribute === undefined && spreadCanProvideTarget) {
    if (!allowsWildcard) {
      const diagnostic = projectionTargetUnbounded(kind);
      diagnostics.push({
        code: "projection-target-unbounded",
        severity: "error",
        ...diagnostic,
        path,
        ...point,
      });
      return;
    }
    sites.push({
      path,
      kind,
      allowedTargets: null,
      ...point,
      offset: openingOffset(source, opening),
    });
    return;
  }
  if (
    targetAttribute === undefined || targetAttribute.initializer === undefined
  ) {
    const diagnostic = projectionAttributeMissing(kind);
    diagnostics.push({
      code: "projection-target-missing",
      severity: "error",
      ...diagnostic,
      path,
      ...point,
    });
    return;
  }
  const targetIndex = properties.indexOf(targetAttribute);
  const overridden = properties.slice(targetIndex + 1).some(
    ts.isJsxSpreadAttribute,
  );
  const literalTarget = overridden ? null : literal(targetAttribute);
  if (literalTarget === "") {
    const diagnostic = projectionAttributeMissing(kind);
    diagnostics.push({
      code: "projection-target-empty",
      severity: "error",
      ...diagnostic,
      path,
      ...point,
    });
    return;
  }
  let allowedTargets: readonly string[] | null;
  if (literalTarget !== null) {
    allowedTargets = [literalTarget];
  } else if (
    !overridden &&
    ts.isJsxExpression(targetAttribute.initializer) &&
    targetAttribute.initializer.expression !== undefined
  ) {
    const result = targetsFromResult(
      kind,
      evaluateTypeScript(
        targetAttribute.initializer.expression,
        source,
        modules,
        expressionScope(opening, source),
      ),
    );
    if ("status" in result && result.status === "invalid") {
      diagnostics.push({
        code: result.code,
        severity: "error",
        message: result.message,
        hint: projectionUsageHint(),
        path,
        ...point,
      });
      return;
    }
    if ("status" in result) {
      if (!allowsWildcard) {
        const diagnostic = projectionTargetUnbounded(kind);
        diagnostics.push({
          code: "projection-target-unbounded",
          severity: "error",
          ...diagnostic,
          path,
          ...point,
        });
        return;
      }
      allowedTargets = null;
    } else {
      allowedTargets = result;
    }
  } else {
    if (!allowsWildcard) {
      const diagnostic = projectionTargetUnbounded(kind);
      diagnostics.push({
        code: "projection-target-unbounded",
        severity: "error",
        ...diagnostic,
        path,
        ...point,
      });
      return;
    }
    allowedTargets = null;
  }
  sites.push({
    path,
    kind,
    allowedTargets,
    ...point,
    offset: openingOffset(source, opening),
  });
};

for (const { path, source } of modules.values()) {
  const visit = (node: ts.Node): void => {
    const targetNode = moduleNode(node);
    const target = targetNode === undefined ? null : moduleTarget(targetNode);
    if (
      targetNode !== undefined && target !== null &&
      modules.targetEscapes(path, target)
    ) {
      diagnostics.push({
        code: "module-path-outside-project",
        severity: "error",
        message: `Local module target ${
          JSON.stringify(target)
        } leaves the view project`,
        path,
        ...sourcePoint(source, targetNode),
      });
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(source).toLowerCase();
      const point = sourcePoint(source, node);
      const authoredSite = attributes(node, "data-marimo-studio-site");
      const valueAttribute = attributes(node, "mo-value")[0];
      const isProjectionElement = tag === "marimo-cell" ||
        tag === "marimo-output";
      if (authoredSite.length > 0) {
        diagnostics.push({
          code: "projection-site-reserved",
          severity: "error",
          message: "data-marimo-studio-site is reserved for Studio",
          path,
          ...point,
        });
      } else if (isProjectionElement && valueAttribute !== undefined) {
        const diagnostic = projectionKindConflict(
          tag as "marimo-cell" | "marimo-output",
        );
        diagnostics.push({
          code: "projection-kind-conflict",
          severity: "error",
          ...diagnostic,
          path,
          ...point,
        });
      } else if (tag === "marimo-cell") {
        reportTarget(path, source, node, "cell", "name");
      } else if (tag === "marimo-output") {
        reportTarget(path, source, node, "output", "value");
      }
      if (!isProjectionElement && valueAttribute !== undefined) {
        reportTarget(path, source, node, "value", "mo-value");
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
}

console.log(JSON.stringify({ schema: 2, sites, diagnostics }));
