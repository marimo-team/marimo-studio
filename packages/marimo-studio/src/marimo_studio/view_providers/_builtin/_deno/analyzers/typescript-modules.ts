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
  readonly expression: ts.Expression | null;
};

const scriptKind = (path: string): ts.ScriptKind =>
  path.endsWith(".tsx")
    ? ts.ScriptKind.TSX
    : path.endsWith(".jsx")
    ? ts.ScriptKind.JSX
    : path.endsWith(".ts")
    ? ts.ScriptKind.TS
    : ts.ScriptKind.JS;

type BindingDeclaration =
  | ts.VariableDeclaration
  | ts.ParameterDeclaration
  | ts.BindingElement;

const declarations = (
  source: ts.SourceFile,
  name: string,
): BindingDeclaration[] => {
  const matches: BindingDeclaration[] = [];
  const visit = (node: ts.Node): void => {
    if (
      (ts.isVariableDeclaration(node) || ts.isParameter(node) ||
        ts.isBindingElement(node)) &&
      ts.isIdentifier(node.name) && node.name.text === name
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

const lexicalContainer = (node: BindingDeclaration): ts.Node => {
  let owner: ts.Node = node;
  while (ts.isBindingElement(owner) || ts.isBindingPattern(owner)) {
    owner = owner.parent;
  }
  if (ts.isVariableDeclaration(owner) && ts.isCatchClause(owner.parent)) {
    return owner.parent;
  }
  const blockScoped = !ts.isVariableDeclaration(owner) ||
    (ts.getCombinedNodeFlags(owner.parent) & ts.NodeFlags.BlockScoped) !== 0;
  let current = owner.parent;
  while (current !== undefined) {
    if (!blockScoped && ts.isFunctionLike(current) && "body" in current) {
      return current.body ?? current;
    }
    if (
      ts.isSourceFile(current) || ts.isFunctionLike(current) ||
      ts.isClassStaticBlockDeclaration(current) || ts.isModuleBlock(current) ||
      (blockScoped && (ts.isBlock(current) || ts.isCaseBlock(current) ||
        ts.isForStatement(current) || ts.isForOfStatement(current) ||
        ts.isForInStatement(current)))
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
        (declaration) => contains(lexicalContainer(declaration), identifier),
      )
      .sort((left, right) => {
        const leftScope = lexicalContainer(left);
        const rightScope = lexicalContainer(right);
        return (leftScope.end - leftScope.pos) -
            (rightScope.end - rightScope.pos) ||
          right.getStart(source) - left.getStart(source);
      });
    const declaration = available[0];
    if (declaration === undefined) return null;
    const expression = ts.isVariableDeclaration(declaration) &&
        (ts.getCombinedNodeFlags(declaration.parent) & ts.NodeFlags.Const) !==
          0 &&
        declaration.getStart(source) < identifier.getStart(source)
      ? declaration.initializer ?? null
      : null;
    return { source, expression };
  }

  exportedBinding(
    source: ts.SourceFile,
    name: string,
  ): TypeScriptBinding | null {
    for (const declaration of declarations(source, name)) {
      if (
        !ts.isVariableDeclaration(declaration) ||
        declaration.initializer === undefined ||
        (ts.getCombinedNodeFlags(declaration.parent) & ts.NodeFlags.Const) === 0
      ) continue;
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
