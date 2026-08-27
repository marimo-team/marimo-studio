import ts from "npm:typescript@6.0.3";

import {
  arrayItems,
  bounded,
  dynamic,
  otherValue,
  propertyValues,
  type StaticResult,
  type StaticValue,
  stringValue,
} from "./static-values.ts";
import { TypeScriptModules } from "./typescript-modules.ts";

export type TypeScriptScope = ReadonlyMap<string, StaticResult>;

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

export const evaluateTypeScript = (
  expression: ts.Expression,
  source: ts.SourceFile,
  modules: TypeScriptModules,
  scope: TypeScriptScope = new Map(),
  seen: ReadonlySet<ts.Node> = new Set(),
): StaticResult => {
  if (seen.has(expression)) return dynamic();
  const nextSeen = new Set(seen).add(expression);
  if (
    ts.isParenthesizedExpression(expression) ||
    ts.isAsExpression(expression) ||
    ts.isSatisfiesExpression(expression) ||
    ts.isNonNullExpression(expression) ||
    ts.isTypeAssertionExpression(expression)
  ) {
    return evaluateTypeScript(
      expression.expression,
      source,
      modules,
      scope,
      nextSeen,
    );
  }
  if (
    ts.isStringLiteral(expression) ||
    ts.isNoSubstitutionTemplateLiteral(expression)
  ) {
    return bounded(stringValue(expression.text));
  }
  if (
    ts.isNumericLiteral(expression) ||
    expression.kind === ts.SyntaxKind.TrueKeyword ||
    expression.kind === ts.SyntaxKind.FalseKeyword ||
    expression.kind === ts.SyntaxKind.NullKeyword
  ) {
    return bounded(otherValue());
  }
  if (ts.isArrayLiteralExpression(expression)) {
    const items: StaticValue[] = [];
    for (const element of expression.elements) {
      if (ts.isOmittedExpression(element)) return dynamic();
      if (ts.isSpreadElement(element)) {
        const spread = arrayItems(
          evaluateTypeScript(
            element.expression,
            source,
            modules,
            scope,
            nextSeen,
          ),
        );
        if (spread.status !== "bounded") return spread;
        items.push(...spread.values);
        continue;
      }
      const item = evaluateTypeScript(
        element,
        source,
        modules,
        scope,
        nextSeen,
      );
      if (item.status !== "bounded" || item.values.length !== 1) return item;
      items.push(item.values[0]);
    }
    return bounded({ kind: "array", items });
  }
  if (ts.isObjectLiteralExpression(expression)) {
    const entries = new Map<string, StaticValue>();
    for (const property of expression.properties) {
      if (ts.isSpreadAssignment(property)) {
        const spread = evaluateTypeScript(
          property.expression,
          source,
          modules,
          scope,
          nextSeen,
        );
        if (spread.status !== "bounded" || spread.values.length !== 1) {
          return spread;
        }
        const value = spread.values[0];
        if (value.kind !== "record") return dynamic();
        for (const entry of value.entries) entries.set(...entry);
        continue;
      }
      const name = property.name !== undefined &&
          (ts.isIdentifier(property.name) ||
            ts.isStringLiteral(property.name) ||
            ts.isNumericLiteral(property.name))
        ? property.name.text
        : null;
      if (name === null) return dynamic();
      const value = ts.isPropertyAssignment(property)
        ? evaluateTypeScript(
          property.initializer,
          source,
          modules,
          scope,
          nextSeen,
        )
        : ts.isShorthandPropertyAssignment(property)
        ? evaluateTypeScript(property.name, source, modules, scope, nextSeen)
        : dynamic();
      if (value.status !== "bounded" || value.values.length !== 1) return value;
      entries.set(name, value.values[0]);
    }
    return bounded({ kind: "record", entries });
  }
  if (ts.isIdentifier(expression)) {
    const scoped = scope.get(expression.text);
    if (scoped !== undefined) return scoped;
    const binding = modules.localBinding(expression, source) ??
      modules.importedBinding(expression, source);
    return binding === null ? dynamic() : evaluateTypeScript(
      binding.expression,
      binding.source,
      modules,
      new Map(),
      nextSeen,
    );
  }
  if (ts.isPropertyAccessExpression(expression)) {
    return propertyValues(
      evaluateTypeScript(
        expression.expression,
        source,
        modules,
        scope,
        nextSeen,
      ),
      expression.name.text,
    );
  }
  if (
    ts.isElementAccessExpression(expression) &&
    expression.argumentExpression !== undefined
  ) {
    const object = evaluateTypeScript(
      expression.expression,
      source,
      modules,
      scope,
      nextSeen,
    );
    const argument = evaluateTypeScript(
      expression.argumentExpression,
      source,
      modules,
      scope,
      nextSeen,
    );
    if (argument.status !== "bounded" || argument.values.length !== 1) {
      return dynamic();
    }
    const member = argument.values[0];
    return member.kind === "string"
      ? propertyValues(object, member.value)
      : dynamic();
  }
  if (ts.isConditionalExpression(expression)) {
    return combine([
      evaluateTypeScript(expression.whenTrue, source, modules, scope, nextSeen),
      evaluateTypeScript(
        expression.whenFalse,
        source,
        modules,
        scope,
        nextSeen,
      ),
    ]);
  }
  if (ts.isCallExpression(expression)) {
    if (
      ts.isPropertyAccessExpression(expression.expression) &&
      ts.isIdentifier(expression.expression.expression) &&
      expression.expression.expression.text === "Object" &&
      expression.expression.name.text === "values" &&
      expression.arguments.length === 1
    ) {
      const record = evaluateTypeScript(
        expression.arguments[0],
        source,
        modules,
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
      ts.isPropertyAccessExpression(expression.expression) &&
      expression.expression.name.text === "filter"
    ) {
      return evaluateTypeScript(
        expression.expression.expression,
        source,
        modules,
        scope,
        nextSeen,
      );
    }
  }
  return dynamic();
};
