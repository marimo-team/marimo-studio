import { resolve } from "node:path";
import { parse } from "npm:svelte@5.56.9/compiler";

import {
  arrayItems,
  bounded,
  dynamic,
  otherValue,
  type ProjectionKind,
  propertyValues,
  type StaticResult,
  type StaticValue,
  stringValue,
  targetsFromResult,
} from "../_deno/analyzers/static-values.ts";
import { TypeScriptModules } from "../_deno/analyzers/typescript-modules.ts";
import { evaluateTypeScript } from "../_deno/analyzers/typescript-values.ts";

type Diagnostic = {
  readonly code: string;
  readonly severity: "error" | "warning";
  readonly message: string;
  readonly path?: string;
  readonly line?: number;
  readonly column?: number;
};

type Site = {
  readonly path: string;
  readonly kind: ProjectionKind;
  readonly allowedTargets: readonly string[] | null;
  readonly line: number;
  readonly column: number;
  readonly offset: number;
};

type AstNode = {
  readonly type?: string;
  start?: number;
  end?: number;
  readonly name?: string;
  readonly kind?: string;
  readonly attributes?: readonly AstNode[];
  readonly value?: unknown;
  readonly data?: string;
  readonly raw?: string;
  readonly expression?: AstNode;
  readonly argument?: AstNode;
  readonly arguments?: readonly AstNode[];
  readonly callee?: AstNode;
  readonly object?: AstNode;
  readonly property?: AstNode;
  readonly computed?: boolean;
  readonly elements?: readonly (AstNode | null)[];
  readonly properties?: readonly AstNode[];
  readonly key?: AstNode;
  readonly init?: AstNode;
  readonly id?: AstNode;
  readonly declarations?: readonly AstNode[];
  readonly body?: AstNode | readonly AstNode[];
  readonly source?: AstNode;
  readonly specifiers?: readonly AstNode[];
  readonly imported?: AstNode;
  readonly local?: AstNode;
  readonly context?: AstNode;
  readonly consequent?: AstNode;
  readonly alternate?: AstNode;
  readonly [key: string]: unknown;
};

type SvelteDocument = {
  readonly kind: "svelte";
  readonly path: string;
  readonly source: string;
  readonly root: AstNode;
};

type Scope = ReadonlyMap<string, StaticResult>;

const [rootPath, ...files] = Deno.args;
if (!rootPath) throw new Error("Analyzer requires a project root");

const sites: Site[] = [];
const diagnostics: Diagnostic[] = [];
const encoder = new TextEncoder();
const documents = new Map<string, SvelteDocument>();
const modules = new TypeScriptModules(rootPath);

const pointAt = (
  source: string,
  offset: number,
): { line: number; column: number } => {
  const prefix = source.slice(0, offset);
  const lines = prefix.split("\n");
  return { line: lines.length, column: lines.at(-1)!.length + 1 };
};

const adjustBomOffsets = (root: AstNode): void => {
  const adjusted = new WeakSet<object>();
  const adjust = (value: unknown): void => {
    if (value === null || typeof value !== "object" || adjusted.has(value)) {
      return;
    }
    adjusted.add(value);
    if (Array.isArray(value)) {
      value.forEach(adjust);
      return;
    }
    const node = value as AstNode;
    if (typeof node.start === "number") node.start += 1;
    if (typeof node.end === "number") node.end += 1;
    Object.values(node).forEach(adjust);
  };
  adjust(root);
};

for (const path of files) {
  let source: string;
  try {
    source = await Deno.readTextFile(resolve(rootPath, path));
  } catch (error) {
    diagnostics.push({
      code: "source-read-failed",
      severity: "error",
      message: error instanceof Error ? error.message : String(error),
      path,
    });
    continue;
  }
  if (!path.endsWith(".svelte")) {
    modules.add(path, source);
    continue;
  }
  try {
    const parseSource = source.charCodeAt(0) === 0xfeff
      ? source.slice(1)
      : source;
    const root = parse(parseSource, { modern: true }) as unknown as AstNode;
    if (parseSource !== source) adjustBomOffsets(root);
    documents.set(path, { kind: "svelte", path, source, root });
  } catch (error) {
    const candidate = error as {
      message?: string;
      start?: { line?: number; column?: number };
    };
    diagnostics.push({
      code: "svelte-parse-failed",
      severity: "error",
      message: candidate.message ?? String(error),
      path,
      line: candidate.start?.line,
      column: candidate.start?.column === undefined
        ? undefined
        : candidate.start.column + 1,
    });
  }
}

const reportModuleTarget = (
  path: string,
  source: string,
  node: AstNode,
  target: string,
): void => {
  if (!modules.targetEscapes(path, target)) return;
  diagnostics.push({
    code: "module-path-outside-project",
    severity: "error",
    message: `Local module target ${
      JSON.stringify(target)
    } leaves the view project`,
    path,
    ...pointAt(source, node.start ?? 0),
  });
};

const instanceBody = (document: SvelteDocument): readonly AstNode[] => {
  const instance = document.root.instance as AstNode | undefined;
  const content = instance?.content as AstNode | undefined;
  return Array.isArray(content?.body) ? content.body : [];
};

const variableInitializer = (
  body: readonly AstNode[],
  name: string,
): AstNode | null => {
  for (const statement of body) {
    if (
      statement.type !== "VariableDeclaration" || statement.kind !== "const"
    ) continue;
    for (const declaration of statement.declarations ?? []) {
      if (
        declaration.id?.type === "Identifier" && declaration.id.name === name
      ) {
        return declaration.init ?? null;
      }
    }
  }
  return null;
};

const importedValue = (
  document: SvelteDocument,
  name: string,
): StaticResult | null => {
  for (const statement of instanceBody(document)) {
    if (statement.type !== "ImportDeclaration") continue;
    const local = statement.source?.value;
    if (typeof local !== "string") continue;
    for (const specifier of statement.specifiers ?? []) {
      if (
        specifier.type !== "ImportSpecifier" || specifier.local?.name !== name
      ) continue;
      const imported = specifier.imported?.name;
      if (typeof imported !== "string") return dynamic();
      const module = modules.resolve(document.path, local);
      if (module === null) return dynamic();
      const binding = modules.exportedBinding(module.source, imported);
      return binding === null
        ? dynamic()
        : evaluateTypeScript(binding.expression, binding.source, modules);
    }
  }
  return null;
};

const combine = (results: readonly StaticResult[]): StaticResult => {
  const invalidResult = results.find((result) => result.status === "invalid");
  if (invalidResult !== undefined) return invalidResult;
  if (results.some((result) => result.status === "dynamic")) return dynamic();
  return bounded(
    ...results.flatMap((
      result,
    ) => (result.status === "bounded" ? result.values : [])),
  );
};

const propertyName = (node: AstNode | undefined): string | null => {
  if (node?.type === "Identifier" && typeof node.name === "string") {
    return node.name;
  }
  if (node?.type === "Literal" && typeof node.value === "string") {
    return node.value;
  }
  return null;
};

const evaluate = (
  expression: AstNode,
  document: SvelteDocument,
  scope: Scope,
  seen: ReadonlySet<object> = new Set(),
): StaticResult => {
  if (seen.has(expression)) return dynamic();
  const nextSeen = new Set(seen).add(expression);
  if (
    expression.type === "TSAsExpression" ||
    expression.type === "TSSatisfiesExpression" ||
    expression.type === "TSNonNullExpression" ||
    expression.type === "ChainExpression"
  ) {
    return expression.expression === undefined
      ? dynamic()
      : evaluate(expression.expression, document, scope, nextSeen);
  }
  if (expression.type === "Literal") {
    return typeof expression.value === "string"
      ? bounded(stringValue(expression.value))
      : bounded(otherValue());
  }
  if (expression.type === "TemplateLiteral") {
    const expressions = expression.expressions as
      | readonly AstNode[]
      | undefined;
    const quasis = expression.quasis as readonly AstNode[] | undefined;
    if ((expressions?.length ?? 0) === 0 && quasis?.length === 1) {
      const cooked = (quasis[0].value as AstNode | undefined)?.cooked;
      if (typeof cooked === "string") return bounded(stringValue(cooked));
    }
    return dynamic();
  }
  if (expression.type === "ArrayExpression") {
    const items: StaticValue[] = [];
    for (const element of expression.elements ?? []) {
      if (element === null || element.type === "SpreadElement") {
        return dynamic();
      }
      const value = evaluate(element, document, scope, nextSeen);
      if (value.status !== "bounded" || value.values.length !== 1) return value;
      items.push(value.values[0]);
    }
    return bounded({ kind: "array", items });
  }
  if (expression.type === "ObjectExpression") {
    const entries = new Map<string, StaticValue>();
    for (const property of expression.properties ?? []) {
      if (property.type !== "Property" || property.value === undefined) {
        return dynamic();
      }
      const name = propertyName(property.key);
      if (name === null) return dynamic();
      const value = evaluate(
        property.value as AstNode,
        document,
        scope,
        nextSeen,
      );
      if (value.status !== "bounded" || value.values.length !== 1) return value;
      entries.set(name, value.values[0]);
    }
    return bounded({ kind: "record", entries });
  }
  if (expression.type === "Identifier" && typeof expression.name === "string") {
    const scoped = scope.get(expression.name);
    if (scoped !== undefined) return scoped;
    const initializer = variableInitializer(
      instanceBody(document),
      expression.name,
    );
    if (initializer !== null) {
      return evaluate(initializer, document, scope, nextSeen);
    }
    return importedValue(document, expression.name) ?? dynamic();
  }
  if (
    expression.type === "MemberExpression" && expression.object !== undefined
  ) {
    const property = propertyName(expression.property);
    if (property === null) return dynamic();
    return propertyValues(
      evaluate(expression.object, document, scope, nextSeen),
      property,
    );
  }
  if (expression.type === "ConditionalExpression") {
    return expression.consequent === undefined ||
        expression.alternate === undefined
      ? dynamic()
      : combine([
        evaluate(expression.consequent, document, scope, nextSeen),
        evaluate(expression.alternate, document, scope, nextSeen),
      ]);
  }
  if (expression.type === "CallExpression" && expression.callee !== undefined) {
    const callee = expression.callee;
    if (
      callee.type === "MemberExpression" &&
      callee.object?.type === "Identifier" &&
      callee.object.name === "Object" &&
      propertyName(callee.property) === "values" &&
      expression.arguments?.length === 1
    ) {
      const record = evaluate(
        expression.arguments[0],
        document,
        scope,
        nextSeen,
      );
      if (record.status !== "bounded") return record;
      const values: StaticValue[] = [];
      for (const value of record.values) {
        if (value.kind !== "record") return dynamic();
        values.push(...value.entries.values());
      }
      return bounded({ kind: "array", items: values });
    }
    if (
      callee.type === "MemberExpression" &&
      propertyName(callee.property) === "filter" &&
      callee.object !== undefined
    ) {
      return evaluate(callee.object, document, scope, nextSeen);
    }
  }
  return dynamic();
};

const bindPattern = (
  pattern: AstNode,
  values: StaticResult,
  scope: Map<string, StaticResult>,
): void => {
  if (pattern.type === "Identifier" && typeof pattern.name === "string") {
    scope.set(pattern.name, values);
    return;
  }
  if (pattern.type !== "ObjectPattern") return;
  for (const property of pattern.properties ?? []) {
    if (property.type !== "Property") continue;
    const local = property.value as AstNode | undefined;
    const key = propertyName(property.key);
    if (
      local?.type === "Identifier" && typeof local.name === "string" &&
      key !== null
    ) {
      scope.set(local.name, propertyValues(values, key));
    }
  }
};

const openingOffset = (source: string, node: AstNode): number => {
  const attributeEnds = (node.attributes ?? []).flatMap((attribute) =>
    typeof attribute.end === "number" ? [attribute.end] : []
  );
  const insertion = attributeEnds.length > 0
    ? Math.max(...attributeEnds)
    : (node.start ?? 0) + 1 + (node.name?.length ?? 0);
  return encoder.encode(source.slice(0, insertion)).length;
};

const attributes = (node: AstNode, name: string): AstNode[] =>
  node.attributes?.filter((item) =>
    item.type === "Attribute" && item.name === name
  ) ?? [];

const literal = (item: AstNode): string | null => {
  const values = Array.isArray(item.value) ? item.value : [item.value];
  if (values.length !== 1) return null;
  const value = values[0] as AstNode;
  if (value.type !== "Text") return null;
  const result = typeof value.data === "string"
    ? value.data
    : typeof value.raw === "string"
    ? value.raw
    : null;
  return result?.trim() ?? null;
};

const attributeExpression = (item: AstNode): AstNode | null => {
  if (
    Array.isArray(item.value) || typeof item.value !== "object" ||
    item.value === null
  ) {
    return null;
  }
  const value = item.value as AstNode;
  return value.type === "ExpressionTag" && value.expression !== undefined
    ? value.expression
    : null;
};

const reportTarget = (
  document: SvelteDocument,
  node: AstNode,
  kind: ProjectionKind,
  attributeName: string,
  scope: Scope,
): void => {
  const point = pointAt(document.source, node.start ?? 0);
  const wildcardAttributes = attributes(node, "data-marimo-allow");
  const allowsWildcard = wildcardAttributes.length === 1 &&
    literal(wildcardAttributes[0]) === "*";
  if (
    wildcardAttributes.length > 1 ||
    (wildcardAttributes.length === 1 && !allowsWildcard)
  ) {
    diagnostics.push({
      code: "projection-wildcard-invalid",
      severity: "error",
      message: 'data-marimo-allow must be the literal "*"',
      path: document.path,
      ...point,
    });
    return;
  }
  const matches = attributes(node, attributeName);
  if (matches.length > 1) {
    diagnostics.push({
      code: "projection-target-duplicate",
      severity: "error",
      message: `${kind} projection declares ${attributeName} more than once`,
      path: document.path,
      ...point,
    });
    return;
  }
  const targetAttribute = matches[0];
  const allAttributes = node.attributes ?? [];
  const spreadCanProvideTarget = allAttributes.some((item) =>
    item.type === "SpreadAttribute"
  );
  if (targetAttribute === undefined && spreadCanProvideTarget) {
    if (!allowsWildcard) {
      diagnostics.push({
        code: "projection-target-unbounded",
        severity: "error",
        message: 'Unbounded projection targets require data-marimo-allow="*"',
        path: document.path,
        ...point,
      });
      return;
    }
    sites.push({
      path: document.path,
      kind,
      allowedTargets: null,
      ...point,
      offset: openingOffset(document.source, node),
    });
    return;
  }
  if (targetAttribute === undefined || targetAttribute.value === true) {
    diagnostics.push({
      code: "projection-target-missing",
      severity: "error",
      message: `${kind} projection requires an explicit target attribute`,
      path: document.path,
      ...point,
    });
    return;
  }
  const targetIndex = allAttributes.indexOf(targetAttribute);
  const overridden = allAttributes
    .slice(targetIndex + 1)
    .some((item) => item.type === "SpreadAttribute");
  const literalTarget = overridden ? null : literal(targetAttribute);
  if (literalTarget === "") {
    diagnostics.push({
      code: "projection-target-empty",
      severity: "error",
      message: `${kind} projection target must not be empty`,
      path: document.path,
      ...point,
    });
    return;
  }
  let allowedTargets: readonly string[] | null;
  if (literalTarget !== null) {
    allowedTargets = [literalTarget];
  } else {
    const expression = overridden ? null : attributeExpression(targetAttribute);
    const result = expression === null
      ? { status: "dynamic" as const }
      : targetsFromResult(kind, evaluate(expression, document, scope));
    if ("status" in result && result.status === "invalid") {
      diagnostics.push({
        code: result.code,
        severity: "error",
        message: result.message,
        path: document.path,
        ...point,
      });
      return;
    }
    if ("status" in result) {
      if (!allowsWildcard) {
        diagnostics.push({
          code: "projection-target-unbounded",
          severity: "error",
          message: 'Unbounded projection targets require data-marimo-allow="*"',
          path: document.path,
          ...point,
        });
        return;
      }
      allowedTargets = null;
    } else {
      allowedTargets = result;
    }
  }
  sites.push({
    path: document.path,
    kind,
    allowedTargets,
    ...point,
    offset: openingOffset(document.source, node),
  });
};

const inspectElement = (
  document: SvelteDocument,
  node: AstNode,
  scope: Scope,
): void => {
  const point = pointAt(document.source, node.start ?? 0);
  const authoredSite = attributes(node, "data-marimo-studio-site");
  const valueAttribute = attributes(node, "mo-value")[0];
  const tag = node.name?.toLowerCase();
  const isProjectionElement = tag === "marimo-cell" || tag === "marimo-output";
  if (authoredSite.length > 0) {
    diagnostics.push({
      code: "projection-site-reserved",
      severity: "error",
      message: "data-marimo-studio-site is reserved for Studio",
      path: document.path,
      ...point,
    });
  } else if (isProjectionElement && valueAttribute !== undefined) {
    diagnostics.push({
      code: "projection-kind-conflict",
      severity: "error",
      message: "One element cannot own two projection kinds",
      path: document.path,
      ...point,
    });
  } else if (tag === "marimo-cell") {
    reportTarget(document, node, "cell", "name", scope);
  } else if (tag === "marimo-output") {
    reportTarget(document, node, "output", "value", scope);
  }
  if (!isProjectionElement && valueAttribute !== undefined) {
    reportTarget(document, node, "value", "mo-value", scope);
  }
};

for (const document of documents.values()) {
  if (document.kind !== "svelte") continue;
  for (const statement of instanceBody(document)) {
    if (statement.type !== "ImportDeclaration") continue;
    const target = statement.source?.value;
    if (typeof target === "string" && statement.source !== undefined) {
      reportModuleTarget(
        document.path,
        document.source,
        statement.source,
        target,
      );
    }
  }
  const seen = new WeakSet<object>();
  const visit = (value: unknown, scope: Scope): void => {
    if (value === null || typeof value !== "object" || seen.has(value)) return;
    seen.add(value);
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, scope));
      return;
    }
    const node = value as AstNode;
    if (
      node.type === "EachBlock" && node.expression !== undefined &&
      node.context !== undefined
    ) {
      const eachScope = new Map(scope);
      bindPattern(
        node.context,
        arrayItems(evaluate(node.expression, document, scope)),
        eachScope,
      );
      visit(node.body, eachScope);
      visit(node.fallback, scope);
      return;
    }
    if (node.type === "RegularElement") inspectElement(document, node, scope);
    Object.values(node).forEach((item) => visit(item, scope));
  };
  visit(document.root, new Map());
}

console.log(JSON.stringify({ schema: 2, sites, diagnostics }));
