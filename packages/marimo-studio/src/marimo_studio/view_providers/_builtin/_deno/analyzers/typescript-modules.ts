import {
  dirname,
  extname,
  isAbsolute,
  relative,
  resolve,
  sep,
} from "node:path";
import ts from "npm:typescript@6.0.3";

export type TypeScriptDocument = {
  readonly path: string;
  readonly source: ts.SourceFile;
};

export type TypeScriptBinding = {
  readonly source: ts.SourceFile;
  readonly expression: ts.Expression;
};

const scriptKind = (path: string): ts.ScriptKind =>
  path.endsWith(".tsx")
    ? ts.ScriptKind.TSX
    : path.endsWith(".jsx")
    ? ts.ScriptKind.JSX
    : path.endsWith(".ts")
    ? ts.ScriptKind.TS
    : ts.ScriptKind.JS;

const declarations = (
  source: ts.SourceFile,
  name: string,
): ts.VariableDeclaration[] => {
  const matches: ts.VariableDeclaration[] = [];
  const visit = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === name &&
      node.initializer !== undefined &&
      (ts.getCombinedNodeFlags(node.parent) & ts.NodeFlags.Const) !== 0
    ) {
      matches.push(node);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return matches;
};

const contains = (container: ts.Node, node: ts.Node): boolean =>
  container.pos <= node.pos && node.end <= container.end;

const lexicalContainer = (node: ts.Node): ts.Node => {
  let current = node.parent;
  while (current !== undefined) {
    if (
      ts.isSourceFile(current) || ts.isBlock(current) ||
      ts.isFunctionLike(current)
    ) {
      return current;
    }
    current = current.parent;
  }
  return node.getSourceFile();
};

export class TypeScriptModules {
  readonly #root: string;
  readonly #documents = new Map<string, TypeScriptDocument>();

  constructor(root: string) {
    this.#root = resolve(root);
  }

  add(path: string, content: string): TypeScriptDocument {
    const document = {
      path,
      source: ts.createSourceFile(
        path,
        content,
        ts.ScriptTarget.Latest,
        true,
        scriptKind(path),
      ),
    };
    this.#documents.set(path, document);
    return document;
  }

  values(): IterableIterator<TypeScriptDocument> {
    return this.#documents.values();
  }

  projectPath(absolute: string): string | null {
    const projectRelative = relative(this.#root, absolute);
    if (
      projectRelative === ".." ||
      projectRelative.startsWith(`..${sep}`) ||
      isAbsolute(projectRelative)
    ) {
      return null;
    }
    return projectRelative.split(sep).join("/");
  }

  targetEscapes(fromPath: string, target: string): boolean {
    const local = target.split(/[?#]/, 1)[0];
    if (
      local.toLowerCase().startsWith("file:") ||
      isAbsolute(local) ||
      /^[a-zA-Z]:[\\/]/.test(local)
    ) {
      return true;
    }
    return (
      local.startsWith(".") &&
      this.projectPath(
          resolve(dirname(resolve(this.#root, fromPath)), local),
        ) === null
    );
  }

  resolve(fromPath: string, target: string): TypeScriptDocument | null {
    if (!target.startsWith(".")) return null;
    const raw = resolve(dirname(resolve(this.#root, fromPath)), target);
    if (this.projectPath(raw) === null) return null;
    const candidates = extname(raw) ? [raw] : [
      raw,
      ...[".ts", ".tsx", ".js", ".jsx", ".mjs"].map((suffix) => raw + suffix),
      ...[".ts", ".tsx", ".js", ".jsx", ".mjs"].map((suffix) =>
        resolve(raw, `index${suffix}`)
      ),
    ];
    for (const candidate of candidates) {
      const path = this.projectPath(candidate);
      if (path !== null) {
        const document = this.#documents.get(path);
        if (document !== undefined) return document;
      }
    }
    return null;
  }

  localBinding(
    identifier: ts.Identifier,
    source: ts.SourceFile,
  ): TypeScriptBinding | null {
    const available = declarations(source, identifier.text)
      .filter(
        (declaration) =>
          declaration.getStart(source) < identifier.getStart(source) &&
          contains(lexicalContainer(declaration), identifier),
      )
      .sort((left, right) => right.getStart(source) - left.getStart(source));
    const declaration = available[0];
    return declaration?.initializer === undefined
      ? null
      : { source, expression: declaration.initializer };
  }

  exportedBinding(
    source: ts.SourceFile,
    name: string,
  ): TypeScriptBinding | null {
    for (const declaration of declarations(source, name)) {
      const statement = declaration.parent.parent;
      if (
        ts.isVariableStatement(statement) &&
        statement.modifiers?.some((modifier) =>
          modifier.kind === ts.SyntaxKind.ExportKeyword
        )
      ) {
        return { source, expression: declaration.initializer! };
      }
    }
    return null;
  }

  importedBinding(
    identifier: ts.Identifier,
    source: ts.SourceFile,
  ): TypeScriptBinding | null {
    for (const statement of source.statements) {
      if (
        !ts.isImportDeclaration(statement) ||
        !ts.isStringLiteral(statement.moduleSpecifier) ||
        statement.importClause?.namedBindings === undefined ||
        !ts.isNamedImports(statement.importClause.namedBindings)
      ) {
        continue;
      }
      for (const specifier of statement.importClause.namedBindings.elements) {
        if (specifier.name.text !== identifier.text) continue;
        const imported = specifier.propertyName?.text ?? specifier.name.text;
        const module = this.resolve(
          source.fileName,
          statement.moduleSpecifier.text,
        );
        return module === null
          ? null
          : this.exportedBinding(module.source, imported);
      }
    }
    return null;
  }
}
